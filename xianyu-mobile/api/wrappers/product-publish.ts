import { getApiClient } from './client';

const PREFIX = '/api/v1/product-publish';

/** 解开 {success, message, data} 信封（后端业务失败也返回 HTTP 200，靠 success 区分） */
function unwrapData<T>(body: unknown): T {
  if (body && typeof body === 'object' && 'success' in body && 'data' in body) {
    const obj = body as { success: unknown; data: unknown };
    if (obj.success === true || obj.success === 'true') return obj.data as T;
    const msg = (body as { message?: string }).message || '操作失败';
    throw new Error(msg);
  }
  return body as T;
}

/** 从本地 uri 推断扩展名与 MIME 类型 */
function mimeFromUri(uri: string): { name: string; type: string } {
  const ext = (uri.split('.').pop() || 'jpg').toLowerCase().split('?')[0];
  const typeMap: Record<string, string> = {
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    gif: 'image/gif',
    webp: 'image/webp',
    heic: 'image/heic',
    bmp: 'image/bmp',
  };
  return { name: `image.${ext}`, type: typeMap[ext] || 'image/jpeg' };
}

export interface UploadedImages {
  paths: string[];
  urls: string[];
}

/**
 * 上传商品兜底图片（multipart/form-data，字段名 files，多文件）。
 * 返回 {paths, urls}，提交任务时取 urls 填入 material_defaults.images
 * （与 web AiListingTaskPanel 一致：images 存预览 url）。
 * RN FormData 文件字段需 { uri, name, type }，openapi-fetch 识别 FormData 后交由 fetch 自动设置 boundary。
 */
export async function uploadProductImages(uris: string[]): Promise<UploadedImages> {
  if (uris.length === 0) return { paths: [], urls: [] };

  const client = await getApiClient();

  const formData = new FormData();
  uris.forEach((uri) => {
    const { name, type } = mimeFromUri(uri);
    formData.append('files', { uri, name, type } as any);
  });

  const { data } = (await (client.POST as any)(`${PREFIX}/upload/images`, {
    body: formData,
  })) as { data?: unknown };

  return unwrapData<UploadedImages>(data);
}

export interface PublishMaterialOption {
  id: number;
  user_id: number;
  title: string;
  price: number;
  images: string[];
}

export interface PublishMaterialPage {
  list: PublishMaterialOption[];
  total: number;
}

export interface BatchAccountStatus {
  account_id: string;
  total: number;
  success: number;
  failed: number;
  unknown: number;
  skipped: number;
  publishing: number;
  pending: number;
  sync_status: 'pending' | 'running' | 'success' | 'failed' | 'skipped' | 'unknown';
  sync_message: string;
}

export class PublishBatchUnavailableError extends Error {}

export type PublishWindowHours = 1 | 3 | 5 | 12 | 24;

export interface PublishBatchAttempt {
  id: number;
  attempt_no: number;
  status: string;
  window_hours: number | null;
  window_started_at: string | null;
  scheduled_at: string | null;
  deadline_at: string | null;
  request_started_at: string | null;
  schedule_error: string | null;
  minimum_gap_seconds: number;
  error_message?: string | null;
}

export interface PublishBatchTarget {
  id: number;
  account_id: string;
  material_id: number;
  title: string;
  status: string;
  internal_product_id: number | null;
  window_hours: number | null;
  window_started_at: string | null;
  scheduled_at: string | null;
  deadline_at: string | null;
  available_at: string | null;
  request_started_at: string | null;
  minimum_gap_seconds: number;
  schedule_error: string | null;
  error_message?: string | null;
  attempts: PublishBatchAttempt[];
}

export interface PublishBatchTargetPage {
  list: PublishBatchTarget[];
  total: number;
  page: number;
  page_size: number;
}

export interface BatchPublishProgress {
  batch_id: string;
  total: number;
  status?: 'pending' | 'running' | 'success' | 'failed' | 'unknown' | 'partial';
  window_hours: number | null;
  window_started_at: string | null;
  deadline_at: string | null;
  timed_out: number;
  success: number;
  failed: number;
  unknown: number;
  skipped: number;
  publishing: number;
  pending: number;
  finished: boolean;
  snapshot_available: boolean;
  account_statuses: BatchAccountStatus[];
}

export async function getPublishMaterials(page: number, pageSize = 100): Promise<PublishMaterialPage> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(PREFIX + '/materials', {
    params: { query: { page, page_size: pageSize } },
  })) as { data?: unknown };
  const result = unwrapData<PublishMaterialPage>(data);
  if (!result || !Array.isArray(result.list)) throw new Error('素材列表响应无效');
  return result;
}

export async function publishBatch(accountIds: string[], materialIds: number[], windowHours: PublishWindowHours): Promise<{ batch_id: string; total: number }> {
  const client = await getApiClient();
  const { data } = (await (client.POST as any)(PREFIX + '/publish/batch', {
    body: { account_ids: accountIds, material_ids: materialIds, window_hours: windowHours },
  })) as { data?: unknown };
  const result = unwrapData<{ batch_id: string; total: number }>(data);
  if (!result?.batch_id) throw new Error('批量发布响应缺少任务 ID');
  return result;
}

export async function getBatchPublishTargets(batchId: string, page = 1, pageSize = 20): Promise<PublishBatchTargetPage> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(PREFIX + '/publish/batch/' + encodeURIComponent(batchId) + '/targets', {
    params: { query: { page, page_size: pageSize } },
  })) as { data?: unknown };
  const result = unwrapData<PublishBatchTargetPage>(data);
  if (!result || !Array.isArray(result.list)) throw new Error('批量发布详情响应无效');
  return result;
}

export async function retryPublishBatch(batchId: string, targetIds: number[], windowHours: PublishWindowHours): Promise<{ retried: number }> {
  const client = await getApiClient();
  const { data } = (await (client.POST as any)(PREFIX + '/publish/batch/' + encodeURIComponent(batchId) + '/retry', {
    body: { target_ids: targetIds, window_hours: windowHours },
  })) as { data?: unknown };
  const result = unwrapData<{ retried: number }>(data);
  if (!result || !Number.isInteger(result.retried) || result.retried < 0) {
    throw new Error('批量重试响应无效，受理结果无法确认');
  }
  return result;
}

export async function getBatchPublishProgress(batchId: string): Promise<BatchPublishProgress> {
  const client = await getApiClient();
  const { data } = (await (client.GET as any)(PREFIX + '/publish/batch/' + encodeURIComponent(batchId) + '/status')) as { data?: unknown };
  if (data && typeof data === 'object' && (data as { success?: unknown }).success === false) {
    throw new PublishBatchUnavailableError((data as { message?: string }).message || '批量任务状态已失效');
  }
  const result = unwrapData<BatchPublishProgress>(data);
  if (!result?.batch_id) throw new Error('批量发布状态响应无效');
  return result;
}
