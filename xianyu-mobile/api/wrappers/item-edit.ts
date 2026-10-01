import { getApiClient, extractError } from './client';

// ---------------------------------------------------------------------------
// 鱼小铺商品改价 / 编辑（卖家视角）
// 后端路由前缀: /api/v1/items
// ---------------------------------------------------------------------------

/** 单规格改价请求 */
export interface ItemPriceUpdate {
  price: number;
  quantity: number;
}

/** 多规格改价请求 */
export interface ItemSkuPrice {
  sku_id: string;
  price: number;
  quantity: number;
}

export interface ItemPriceUpdateMulti {
  skus: ItemSkuPrice[];
}

/** 商品编辑表单（seller-detail 回填 + seller-edit 提交） */
export interface SellerItemForm {
  title: string;
  description: string;
  price: number;
  original_price?: number;
  images: string[];
  videos?: Array<{ file_id?: string; url?: string; cover?: string; width?: number; height?: number; duration?: number }>;
  specifications?: Array<Record<string, unknown>>;
  sku_rows?: Array<Record<string, unknown>>;
  quantity: number;
  address?: string;
  shipping_method?: 'free' | 'distance' | 'fixed' | 'template' | 'none';
  support_pickup?: boolean;
  postage?: number;
  brand?: string;
  condition?: string;
  platform_title?: string;
  platform_category_id?: string;
  platform_properties?: Array<Record<string, unknown>>;
}

/** 统一解包 { success, data } 包裹格式 */
function unwrap<T>(data: unknown): T | null {
  if (data && typeof data === 'object') {
    const obj = data as Record<string, unknown>;
    if ('data' in obj && obj.data != null) return obj.data as T;
    if ('success' in obj && obj.success === false) return null;
  }
  return (data as T) ?? null;
}

/**
 * 商品改价（单规格传 price+quantity，多规格传 skus 数组）
 */
export async function updateItemPrice(
  cookieId: string,
  itemId: string,
  payload: ItemPriceUpdate | ItemPriceUpdateMulti,
): Promise<{ success: boolean; message?: string }> {
  const client = await getApiClient();
  const { data, error } = (await (client.PUT as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/${encodeURIComponent(itemId)}/price`,
    { body: payload },
  )) as { data?: { success?: boolean; message?: string }; error?: unknown };
  if (error) throw await extractError(error);
  return { success: data?.success ?? true, message: data?.message };
}

/**
 * 获取平台编辑详情（用于编辑表单回填）
 * 仅 is_seller_item=true 的商品可用
 */
export async function getSellerItemDetail(
  cookieId: string,
  itemId: string,
): Promise<{ form: Partial<SellerItemForm> }> {
  const client = await getApiClient();
  const { data, error } = (await (client.GET as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/${encodeURIComponent(itemId)}/seller-detail`,
  )) as { data?: unknown; error?: unknown };
  if (error) throw await extractError(error);
  const body = unwrap<{ form?: Partial<SellerItemForm> }>(data);
  if (!body) throw new Error('获取商品编辑详情失败');
  return body as { form: Partial<SellerItemForm> };
}

/**
 * 提交平台编辑（全量覆盖式提交）
 * 成功后后端自动重新同步该账号商品
 */
export async function updateSellerItem(
  cookieId: string,
  itemId: string,
  form: SellerItemForm,
): Promise<{ success: boolean; message?: string }> {
  const client = await getApiClient();
  const { data, error } = (await (client.PUT as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/${encodeURIComponent(itemId)}/seller-edit`,
    { body: form },
  )) as { data?: { success?: boolean; message?: string }; error?: unknown };
  if (error) throw await extractError(error);
  return { success: data?.success ?? true, message: data?.message };
}

export type ManagedItemEditStatus = 'pending' | 'running' | 'success' | 'failed' | 'unknown' | 'skipped';
export const ITEM_EDIT_WINDOW_HOURS = [1, 3, 5, 12, 24] as const;
export type ItemEditWindowHours = (typeof ITEM_EDIT_WINDOW_HOURS)[number];

export function isItemEditWindowHours(value: unknown): value is ItemEditWindowHours {
  return ITEM_EDIT_WINDOW_HOURS.includes(value as ItemEditWindowHours);
}

function assertItemEditWindowHours(value: ItemEditWindowHours): void {
  if (!isItemEditWindowHours(value)) throw new Error('请选择 1、3、5、12 或 24 小时执行窗口');
}

export interface BatchSellerItemEditPatch {
  title?: string;
  description?: string;
  price?: number;
  original_price?: number | null;
  /** Omit to retain each target's platform images. */
  images?: string[];
  videos?: SellerItemForm['videos'];
  [key: string]: unknown;
}

export interface ManagedItemEditTargetResult {
  id: number;
  account_id: string;
  item_id: string;
  status: ManagedItemEditStatus;
  scheduled_at?: string | null;
  available_at?: string | null;
  deadline_at?: string | null;
  request_started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
  retry_batch_id?: string | null;
}

export interface ManagedItemEditAttemptResult {
  id: number;
  target_id: number;
  status: ManagedItemEditStatus;
  request_started_at?: string | null;
  finished_at?: string | null;
  message?: string | null;
}

export interface ManagedItemEditDetail {
  batch_id: string;
  owner_id?: number;
  status: 'pending' | 'running' | 'finished';
  window_hours: ItemEditWindowHours;
  deadline_at?: string | null;
  payload_snapshot?: BatchSellerItemEditPatch;
  targets: ManagedItemEditTargetResult[];
  attempts?: ManagedItemEditAttemptResult[];
}

export async function createBatchSellerItemEdit(
  cookieId: string,
  itemIds: string[],
  windowHours: 1 | 3 | 5 | 12 | 24,
  patch: BatchSellerItemEditPatch,
  requestId?: string,
): Promise<{ success: boolean; message?: string; batch_id?: string }> {
  assertItemEditWindowHours(windowHours);
  const client = await getApiClient();
  const { data, error } = (await (client.POST as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/batch-seller-edit`,
    { body: { item_ids: itemIds, window_hours: windowHours, patch, request_id: requestId } },
  )) as { data?: { success?: boolean; message?: string; data?: { batch_id?: string } }; error?: unknown };
  if (error) throw await extractError(error);
  return { success: data?.success === true, message: data?.message, batch_id: data?.data?.batch_id };
}

export async function getBatchSellerItemEdit(
  cookieId: string,
  batchId: string,
): Promise<ManagedItemEditDetail> {
  const client = await getApiClient();
  const { data, error } = (await (client.GET as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/batch-seller-edit/${encodeURIComponent(batchId)}`,
  )) as { data?: { success?: boolean; data?: ManagedItemEditDetail; message?: string }; error?: unknown };
  if (error) throw await extractError(error);
  if (data?.success !== true || !data.data) throw new Error(data?.message || '获取批量编辑任务失败');
  return data.data;
}

export async function retryBatchSellerItemEdit(
  cookieId: string,
  batchId: string,
  targetIds: number[],
  windowHours: 1 | 3 | 5 | 12 | 24,
  requestId: string,
): Promise<{ success: boolean; message?: string; batch_id?: string }> {
  assertItemEditWindowHours(windowHours);
  if (!targetIds.length) throw new Error('请选择明确失败的商品后再重试');
  const client = await getApiClient();
  const { data, error } = (await (client.POST as any)(
    `/api/v1/items/${encodeURIComponent(cookieId)}/batch-seller-edit/${encodeURIComponent(batchId)}/retry`,
    { body: { target_ids: targetIds, window_hours: windowHours, request_id: requestId } },
  )) as { data?: { success?: boolean; message?: string; data?: { batch_id?: string } }; error?: unknown };
  if (error) throw await extractError(error);
  return { success: data?.success === true, message: data?.message, batch_id: data?.data?.batch_id };
}

/**
 * 商品批量删除（平台删除 + 本地记录清理）
 * 返回新增的 local_deleted_count / local_failed_ids 供 UI 展示
 */
export async function batchDeleteItems(
  cookieId: string,
  itemIds: string[],
): Promise<{ success: boolean; message?: string; local_deleted_count?: number; local_failed_ids?: string[] }> {
  const client = await getApiClient();
  const { data, error } = (await (client.POST as any)(
    '/api/v1/items/batch-delete-xianyu',
    { body: { cookie_id: cookieId, item_ids: itemIds } },
  )) as {
    data?: {
      success?: boolean;
      message?: string;
      local_deleted_count?: number;
      local_failed_ids?: string[];
    };
    error?: unknown;
  };
  if (error) throw await extractError(error);
  return {
    success: data?.success ?? true,
    message: data?.message,
    local_deleted_count: data?.local_deleted_count,
    local_failed_ids: data?.local_failed_ids,
  };
}
