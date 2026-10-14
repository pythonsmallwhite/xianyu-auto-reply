import { getApiClient, extractError } from './client';
import type { XianyuItem } from './items';

// ---------------------------------------------------------------------------
// 类型定义（与任务规格保持一致）
// ---------------------------------------------------------------------------

export interface ListingTask {
  id: number;
  name: string;
  account_ids: string[];
  status: string;
  /** 后端任务无 name 字段，keyword 才是任务的业务标识 */
  keyword?: string;
  /** 监控类型：listing-上新监控，price_drop-降价监控 */
  monitor_type?: string;
  category_id?: number;
  price_min?: number | null;
  price_max?: number | null;
  interval_minutes?: number;
  is_enabled?: boolean;
}

export interface ListingOverview {
  total_tasks: number;
  active_tasks: number;
  total_items: number;
  /** 今日定时/手动执行总次数（后端 today_run_total） */
  today_run_total?: number;
}

/** 监控分类（用于任务的目标分类展示与新建表单选择） */
export interface ListingCategory {
  id: number;
  name: string;
}

/** 新建上新监控任务的入参（仅覆盖后端必填 + 核心可选字段） */
export interface NewListingTask {
  keyword: string;
  categoryId: number;
  /** 执行间隔（分钟），后端要求 ≥ 1 */
  intervalMinutes: number;
  priceMin?: number;
  priceMax?: number;
  enabled?: boolean;
}

export interface MonitoredItem {
  item_id: string;
  title: string;
  price: string;
  status: string;
  /** 商品所属账号（改价等卖家操作需要）；采集接口未返回时为 undefined */
  cookie_id?: string;
}

export interface ProductItem {
  item_id: string;
  title: string;
  price: string;
  cookie_id: string;
  item_quantity?: number;
  item_status_desc?: string;
  item_sku_count?: number;
  is_seller_item?: boolean;
  item_shelf_time?: string;
  source_category?: XianyuItem['source_category'];
}

// ---------------------------------------------------------------------------
// 通用解析工具
// ---------------------------------------------------------------------------

/**
 * 后端统一响应为 `{ success, message, data }`，抽出内部 data；未包裹则原样返回。
 * 与 accounts.ts / blacklist.ts 中的 unwrapData 保持一致。
 */
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

/**
 * 从可能被包一层 `{ data: [...] }` / `{ items: [...] }` / 裸数组的响应中取出数组。
 * 兼容 ApiResponse 包裹（先 unwrapData 再取数组）与裸返回两种形态。
 */
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
    else if (Array.isArray(obj.rules)) arr = obj.rules;
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
// 商品监控
// ---------------------------------------------------------------------------

function normalizeTask(raw: Record<string, unknown>): ListingTask {
  const statusRaw = raw.status;
  const status =
    statusRaw != null
      ? String(statusRaw)
      : raw.is_enabled != null
        ? raw.is_enabled
          ? 'active'
          : 'inactive'
        : 'unknown';
  return {
    id: num(raw.id ?? raw.task_id),
    name: str(raw.name ?? raw.task_name),
    account_ids: Array.isArray(raw.account_ids)
      ? raw.account_ids.map((a) => String(a))
      : Array.isArray(raw.cookie_ids)
        ? raw.cookie_ids.map((a) => String(a))
        : [],
    status,
    keyword: str(raw.keyword),
    monitor_type: str(raw.monitor_type, 'listing'),
    category_id: raw.category_id != null ? num(raw.category_id) : undefined,
    price_min: raw.price_min != null ? num(raw.price_min) : null,
    price_max: raw.price_max != null ? num(raw.price_max) : null,
    interval_minutes:
      raw.interval_minutes != null ? num(raw.interval_minutes) : undefined,
    is_enabled:
      raw.is_enabled != null
        ? Boolean(raw.is_enabled)
        : status === 'active',
  };
}

/**
 * 获取商品监控任务列表
 *
 * 后端分页查询（GET /api/v1/product-monitor/listing-tasks），响应包在 ApiResponse 里，
 * 内部 data 可能是 `{ data: [...], total }` 也可能是裸数组，两种都兼容。
 * 这里取首页（page_size 较大）以便一次性拿到全部任务用于展示。
 */
export async function getListingTasks(): Promise<ListingTask[]> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    '/api/v1/product-monitor/listing-tasks',
    { params: { query: { page: 1, page_size: 200 } } },
  )) as { data?: unknown; error?: unknown };
  return extractArray<ListingTask>(data, normalizeTask);
}

function normalizeOverview(raw: Record<string, unknown>): ListingOverview {
  return {
    total_tasks: num(
      raw.total_tasks ?? raw.task_count ?? raw.tasks_total ?? raw.tasks,
    ),
    active_tasks: num(
      raw.active_tasks ??
        raw.enabled_tasks ??
        raw.active_task_count ??
        raw.running_tasks ??
        raw.active_count,
    ),
    total_items: num(
      raw.total_items ?? raw.item_count ?? raw.items_total ?? raw.items,
    ),
    today_run_total: num(raw.today_run_total ?? raw.today_runs),
  };
}

/**
 * 获取商品监控概览统计
 *
 * GET /api/v1/product-monitor/listing-tasks/overview
 * 后端返回任务数、活跃任务数、商品数等统计，包在 ApiResponse 中。
 */
export async function getListingOverview(): Promise<ListingOverview> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    '/api/v1/product-monitor/listing-tasks/overview',
  )) as { data?: unknown; error?: unknown };
  const inner = unwrapData<unknown>(data);
  if (inner && typeof inner === 'object') {
    return normalizeOverview(inner as Record<string, unknown>);
  }
  return { total_tasks: 0, active_tasks: 0, total_items: 0 };
}

/** 由采集商品的私信/下单状态派生展示用状态文案 */
function deriveItemStatus(raw: Record<string, unknown>): string {
  const orderState = str(raw.order_state);
  const dmState = str(raw.dm_state);
  if (orderState === 'ordered') return '已下单';
  if (orderState === 'failed') return '下单失败';
  if (orderState === 'duplicate') return '重复下单';
  if (dmState === 'success') return '已私信';
  if (dmState === 'failed') return '私信失败';
  if (dmState === 'pending' || dmState === 'waiting') return '私信中';
  const status = str(raw.status);
  return status || '监控中';
}

function normalizeMonitoredItem(raw: Record<string, unknown>): MonitoredItem {
  return {
    item_id: str(raw.item_id ?? raw.id),
    title: str(raw.title ?? raw.item_title),
    price: str(raw.price ?? raw.item_price, '0'),
    status: deriveItemStatus(raw),
    cookie_id: str(raw.cookie_id ?? raw.account_id) || undefined,
  };
}

/**
 * 获取监控商品项列表
 *
 * GET /api/v1/product-monitor/listing-tasks/items（分页），响应包在 ApiResponse 中。
 * 取首页若干条用于展示最新采集的商品；传入 monitorTaskId 时按任务过滤
 * （后端 query 参数 monitor_task_id）。
 */
export async function getMonitoredItems(
  monitorTaskId?: number,
): Promise<MonitoredItem[]> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    '/api/v1/product-monitor/listing-tasks/items',
    {
      params: {
        query: {
          page: 1,
          page_size: 50,
          ...(monitorTaskId != null
            ? { monitor_task_id: monitorTaskId }
            : {}),
        },
      },
    },
  )) as { data?: unknown; error?: unknown };
  return extractArray<MonitoredItem>(data, normalizeMonitoredItem);
}

// ---------------------------------------------------------------------------
// 上新监控任务管理（新建 / 启停 / 立即执行 / 删除 / 分类）
// ---------------------------------------------------------------------------

/**
 * 断言 ApiResponse 业务成功。后端约定「业务错误也返回 HTTP 200」，
 * 仅凭请求不抛错无法区分成败，需检查 body.success 并抛出 message。
 */
function assertOk(body: unknown): void {
  if (
    body &&
    typeof body === 'object' &&
    (body as Record<string, unknown>).success === false
  ) {
    const msg = str((body as Record<string, unknown>).message);
    throw new Error(msg || '操作失败');
  }
}

/** 获取监控分类列表（GET /api/v1/product-monitor/categories，按用户隔离） */
export async function getListingCategories(): Promise<ListingCategory[]> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(
    '/api/v1/product-monitor/categories',
  )) as { data?: unknown; error?: unknown };
  return extractArray<ListingCategory>(data, (raw) => ({
    id: num(raw.id),
    name: str(raw.name),
  }));
}

/**
 * 新建上新监控任务
 *
 * POST /api/v1/product-monitor/listing-tasks。后端必填：monitor_type/category_id/
 * keyword/interval_minutes，monitor_type 固定传 'listing'（上新监控）。
 * TODO: 采集账号(account_ids)、下单账号(order_account_ids)、私信内容(dm_content)、
 * 直接下单(direct_order)、代理(proxy_url)、上新天数(publish_days)、采集页数
 * (collect_pages)、备注(remark) 等高级字段待后续版本补充。
 */
export async function createListingTask(input: NewListingTask): Promise<void> {
  const client = await getApiClient();
  const { data } = (await (client.POST as any)(
    '/api/v1/product-monitor/listing-tasks',
    {
      body: {
        monitor_type: 'listing',
        category_id: input.categoryId,
        keyword: input.keyword,
        interval_minutes: input.intervalMinutes,
        price_min: input.priceMin ?? null,
        price_max: input.priceMax ?? null,
        is_enabled: input.enabled ?? true,
      },
    },
  )) as { data?: unknown; error?: unknown };
  assertOk(data);
}

/** 启用/停用任务：PUT /api/v1/product-monitor/listing-tasks/{id}/status */
export async function updateListingTaskStatus(
  taskId: number,
  isEnabled: boolean,
): Promise<void> {
  const client = await getApiClient();
  const { data } = (await (client.PUT as any)(
    `/api/v1/product-monitor/listing-tasks/${taskId}/status`,
    { body: { is_enabled: isEnabled } },
  )) as { data?: unknown; error?: unknown };
  assertOk(data);
}

/**
 * 立即执行任务：POST /api/v1/product-monitor/listing-tasks/{id}/run。
 * 后端要求任务处于启用状态，停用任务会以业务失败返回。
 */
export async function runListingTask(taskId: number): Promise<void> {
  const client = await getApiClient();
  const { data } = (await (client.POST as any)(
    `/api/v1/product-monitor/listing-tasks/${taskId}/run`,
  )) as { data?: unknown; error?: unknown };
  assertOk(data);
}

/**
 * 删除任务：后端仅提供批量删除端点 POST /batch-delete，单个删除复用
 * `{ ids: [taskId] }`。
 */
export async function deleteListingTask(taskId: number): Promise<void> {
  const client = await getApiClient();
  const { data } = (await (client.POST as any)(
    '/api/v1/product-monitor/listing-tasks/batch-delete',
    { body: { ids: [taskId] } },
  )) as { data?: unknown; error?: unknown };
  assertOk(data);
}

// ---------------------------------------------------------------------------
// 商品列表（分页）
// ---------------------------------------------------------------------------

function normalizeProductItem(raw: Record<string, unknown>): ProductItem {
  return {
    item_id: str(raw.item_id ?? raw.id),
    title: str(raw.title ?? raw.item_title),
    price: str(raw.price ?? raw.item_price, '0'),
    cookie_id: str(raw.cookie_id ?? raw.account_id),
    source_category: raw.source_category as ProductItem['source_category'],
  };
}

/**
 * 分页获取商品列表
 *
 * GET /api/v1/items/paginated，响应为裸对象，可能形如
 * `{ data: [...], total }` 或被 ApiResponse 包一层，统一兼容。
 */
export async function getProductItems(
  page: number,
  pageSize: number,
  showHistory: boolean = false,
): Promise<{ data: ProductItem[]; total: number }> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)('/api/v1/items/paginated', {
    params: { query: { page, page_size: pageSize, show_history: showHistory } },
  })) as { data?: unknown; error?: unknown };
  const inner = unwrapData<unknown>(data);
  let arr: unknown[] = [];
  let total = 0;
  if (Array.isArray(inner)) {
    arr = inner;
    total = inner.length;
  } else if (inner && typeof inner === 'object') {
    const obj = inner as Record<string, unknown>;
    arr = Array.isArray(obj.data)
      ? obj.data
      : Array.isArray(obj.items)
        ? obj.items
        : Array.isArray(obj.list)
          ? obj.list
          : [];
    total = typeof obj.total === 'number' ? obj.total : arr.length;
  }
  return {
    data: arr.map((item) =>
      normalizeProductItem((item ?? {}) as Record<string, unknown>),
    ),
    total,
  };
}
