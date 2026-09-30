import { getApiClient, extractError } from './client';
export type LinkedListing = {id:number; account_id:string; item_id:string; state:string};
export type LinkedProduct = {id:number; title:string; listings:LinkedListing[]};
export type OfflineTarget = LinkedListing & {status:string; scheduled_at:string; request_started_at?:string; message?:string; schedule_error?:string; retry_batch_id?:string; reconciled_state?:string; reconciled_note?:string; reconciled_at?:string};
export type OfflineDetail = {id:string; finished:boolean; window_hours:number; deadline_at:string; targets:OfflineTarget[]; attempts:{id:number; target_id:number; status:string; message?:string}[]};
export type OfflineReconcileResult = {status:string; listing_state:string|null; conflict:boolean; message?:string};
const root = '/api/v1/internal-products';
async function call<T>(method:'GET'|'POST', url:string, body?:unknown):Promise<T> {
  const client = await getApiClient();
  const {data,error} = await (client[method] as any)(url, body === undefined ? {} : {body});
  if(error) throw await extractError(error);
  if(!data?.success) throw new Error(data?.message || '请求失败');
  return data.data as T;
}
export const listLinkedProducts = () => call<LinkedProduct[]>('GET', root);
export const listOfflineBatches = (id:number) => call<{batch_id:string}[]>('GET', `${root}/${id}/offline-batches`);
export const getOfflineBatch = (id:string) => call<OfflineDetail>('GET', `${root}/offline-batches/${id}`);
export const submitOfflineBatch = (productId:number, ids:number[], hours:number, requestId:string) =>
  call<{batch_id:string}>('POST', `${root}/${productId}/offline-batches`, {listing_ids:ids,window_hours:hours,request_id:requestId,confirmed:true});
export const retryOfflineBatch = (batchId:string, ids:number[], hours:number, requestId:string) =>
  call<{batch_id:string}>('POST', `${root}/offline-batches/${batchId}/retry`, {target_ids:ids,window_hours:hours,request_id:requestId,confirmed:true});
// 人工核对只上报真实平台状态，不补发请求；结论本身即为记录。
export const reconcileOfflineTarget = (batchId:string, targetId:number, platformState:'offline'|'active', note:string) =>
  call<OfflineReconcileResult>('POST', `${root}/offline-batches/${batchId}/targets/${targetId}/reconcile`, {platform_state:platformState,note,confirmed:true});
