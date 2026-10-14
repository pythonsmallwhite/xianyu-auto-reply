import { getApiClient } from './client';

// ---------------------------------------------------------------------------
// 类型定义
// ---------------------------------------------------------------------------

export interface CrawlerJob {
  id: number;
  name: string;
  status: string;
  items_count?: number;
}

export interface CrawlerItem {
  item_id: string;
  title: string;
  price: string;
}

// ---------------------------------------------------------------------------
// 通用解析工具
//
// 后端统一响应为 `{ success, message, data }`，列表可能裸返回数组，也可能被包成
// `{ data: [...] }` / `{ items: [...] }` / `{ records: [...] }`，这里统一兼容。
// ---------------------------------------------------------------------------

/** 取出 `{ success, data }` 包裹的内部 data；未包裹则原样返回。 */
function unwrapData<T>(body: unknown): T {
  if (
    body &&
    typeof body === 'object' &&
    'success' in (body as Record<string, unknown>) &&
    'data' in (body as Record<string, unknown>)
  ) {
    const inner = (body as { data: unknown }).data;
    if (inner != null) return inner as T;
  }
  return body as T;
}

/** 从可能被包一层 / 裸数组的响应中取出数组并逐项归一化。 */
function extractArray<T>(
  data: unknown,
  normalize: (raw: Record<string, unknown>) => T,
): T[] {
  const inner = unwrapData<unknown>(data);
  let arr: unknown[] | null = null;
  if (Array.isArray(inner)) {
    arr = inner;
  } else if (inner && typeof inner === 'object') {
    const obj = inner as Record<string, unknown>;
    if (Array.isArray(obj.data)) arr = obj.data;
    else if (Array.isArray(obj.items)) arr = obj.items;
    else if (Array.isArray(obj.list)) arr = obj.list;
    else if (Array.isArray(obj.records)) arr = obj.records;
  }
  if (!arr) return [];
  return arr.map((item) => normalize((item ?? {}) as Record<string, unknown>));
}

/** 安全取字符串：null/undefined → fallback */
function str(val: unknown, fallback = ''): string {
  if (val == null) return fallback;
  const s = String(val);
  return s === 'undefined' || s === 'null' ? fallback : s;
}

/** 安全取数字 */
function num(val: unknown, fallback = 0): number {
  if (val == null || val === '') return fallback;
  const n = Number(val);
  return Number.isFinite(n) ? n : fallback;
}

// ---------------------------------------------------------------------------
// 爬虫
// ---------------------------------------------------------------------------

function normalizeCrawlerJob(raw: Record<string, unknown>): CrawlerJob {
  const countRaw = raw.items_count ?? raw.item_count ?? raw.total_items ?? raw.count;
  return {
    id: num(raw.id ?? raw.job_id),
    name: str(raw.name ?? raw.job_name),
    status: str(raw.status ?? raw.state, 'unknown'),
    items_count: countRaw != null ? num(countRaw) : undefined,
  };
}

/** 爬虫任务列表：GET /api/v1/goofish/crawler/jobs → `[{ id, name, status, ... }]` */
export async function getCrawlerJobs(): Promise<CrawlerJob[]> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    '/api/v1/goofish/crawler/jobs',
  )) as { data?: unknown; error?: unknown };
  return extractArray<CrawlerJob>(data, normalizeCrawlerJob);
}

function normalizeCrawlerItem(raw: Record<string, unknown>): CrawlerItem {
  return {
    item_id: str(raw.item_id ?? raw.id),
    title: str(raw.title ?? raw.item_title),
    price: str(raw.price ?? raw.item_price, '0'),
  };
}

/** 爬虫任务商品：GET /api/v1/goofish/crawler/jobs/{job_id}/items */
export async function getCrawlerItems(jobId: number): Promise<CrawlerItem[]> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    `/api/v1/goofish/crawler/jobs/${jobId}/items`,
  )) as { data?: unknown; error?: unknown };
  return extractArray<CrawlerItem>(data, normalizeCrawlerItem);
}

/** 启动爬虫：POST /api/v1/goofish/crawler/jobs/{job_id}/start */
export async function startCrawler(jobId: number): Promise<void> {
  const client = await getApiClient();
  await (client.POST as any)(`/api/v1/goofish/crawler/jobs/${jobId}/start`);
}

/** 停止爬虫：POST /api/v1/goofish/crawler/jobs/{job_id}/stop */
export async function stopCrawler(jobId: number): Promise<void> {
  const client = await getApiClient();
  await (client.POST as any)(`/api/v1/goofish/crawler/jobs/${jobId}/stop`);
}
