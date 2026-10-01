import { useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, Clock3, Loader2, RefreshCw, X } from 'lucide-react'
import {
  createBatchSellerItemEdit,
  getBatchSellerItemEdit,
  retryBatchSellerItemEdit,
  type ManagedItemEditResponse,
} from '@/api/items'
import type { Item } from '@/types'
import { useUIStore } from '@/store/uiStore'
import { getApiErrorMessage } from '@/utils/apiError'

type WindowHours = 1 | 3 | 5 | 12 | 24
const WINDOW_OPTIONS: WindowHours[] = [1, 3, 5, 12, 24]
const STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  running: '执行中',
  success: '成功',
  failed: '失败',
  unknown: '结果未知',
  skipped: '已跳过',
}
const EDITABLE_SOURCES = new Set(['managed', 'tool_published_unlinked'])

interface Props {
  items: Item[]
  onClose: () => void
  onCreated: () => void
}

function formatTime(value?: string | null) {
  if (!value) return '未记录'
  return value.replace('T', ' ').replace(/\.\d+$/, '')
}

export default function BatchSellerItemEditModal({ items, onClose, onCreated }: Props) {
  const { addToast } = useUIStore()
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [price, setPrice] = useState('')
  const [images, setImages] = useState('')
  const [windowHours, setWindowHours] = useState<WindowHours | ''>('')
  const [batchId, setBatchId] = useState<string | null>(null)
  const [detail, setDetail] = useState<ManagedItemEditResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [retryWindow, setRetryWindow] = useState<WindowHours | ''>('')
  const [retrying, setRetrying] = useState(false)

  const accountId = items[0]?.cookie_id || ''
  const targetIds = useMemo(() => items.map((item) => item.item_id), [items])
  const invalidReason = useMemo(() => {
    if (!items.length) return '请先选择商品'
    if (!accountId || items.some((item) => item.cookie_id !== accountId)) return '批量编辑必须选择同一账号的商品'
    if (items.some((item) => !EDITABLE_SOURCES.has(item.source_category || ''))) {
      return '历史或来源待确认商品不能加入批量编辑'
    }
    return ''
  }, [accountId, items])
  const failedTargets = (detail?.targets || []).filter((target) => target.status === 'failed')

  const refreshStatus = async (id = batchId) => {
    if (!id) return
    setRefreshing(true)
    try {
      const response = await getBatchSellerItemEdit(accountId, id)
      if (!response.success || !response.data) throw new Error(response.message || '获取批量编辑任务失败')
      setDetail(response.data)
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '获取批量编辑任务失败') })
    } finally {
      setRefreshing(false)
    }
  }

  const handleCreate = async () => {
    if (invalidReason) return addToast({ type: 'warning', message: invalidReason })
    if (!windowHours) return addToast({ type: 'warning', message: '请选择执行时间窗口' })
    if (!title.trim() && !description.trim() && !price.trim() && !images.trim()) {
      return addToast({ type: 'warning', message: '请至少填写一项要修改的内容' })
    }
    if (title.trim().length > 200) return addToast({ type: 'warning', message: '标题不能超过200字' })
    if (description.trim().length > 5000) return addToast({ type: 'warning', message: '描述不能超过5000字' })
    const patch: Record<string, unknown> = {}
    if (title.trim()) patch.title = title.trim()
    if (description.trim()) patch.description = description
    if (price.trim()) {
      const value = Number(price)
      if (!Number.isFinite(value) || value <= 0) return addToast({ type: 'warning', message: '请输入有效价格' })
      patch.price = value
    }
    if (images.trim()) {
      const urls = images.split(/[
,]+/).map((value) => value.trim()).filter(Boolean)
      if (!urls.length || urls.length > 9) return addToast({ type: 'warning', message: '图片地址需为1至9个非空地址' })
      patch.images = urls
    }
    setLoading(true)
    try {
      const response = await createBatchSellerItemEdit(accountId, targetIds, windowHours, patch)
      if (!response.success || !response.data?.batch_id) throw new Error(response.message || '批量编辑任务创建失败')
      setBatchId(response.data.batch_id)
      await refreshStatus(response.data.batch_id)
      addToast({ type: 'success', message: response.message || '批量编辑任务已创建' })
      onCreated()
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '批量编辑任务创建失败') })
    } finally {
      setLoading(false)
    }
  }

  const handleRetry = async () => {
    if (!batchId || !failedTargets.length) return
    if (!retryWindow) return addToast({ type: 'warning', message: '重试前请选择新的执行时间窗口' })
    setRetrying(true)
    try {
      const response = await retryBatchSellerItemEdit(
        accountId,
        batchId,
        failedTargets.map((target) => target.id),
        retryWindow,
        crypto.randomUUID(),
      )
      if (!response.success || !response.data?.batch_id) throw new Error(response.message || '失败项重试创建失败')
      setBatchId(response.data.batch_id)
      setRetryWindow('')
      await refreshStatus(response.data.batch_id)
      addToast({ type: 'success', message: response.message || '失败项已重新排程' })
    } catch (error) {
      addToast({ type: 'error', message: getApiErrorMessage(error, '失败项重试创建失败') })
    } finally {
      setRetrying(false)
    }
  }

  return (
    <div className="modal-overlay z-50">
      <div className="modal-content max-w-3xl max-h-[92vh] flex flex-col">
        <div className="modal-header flex items-center justify-between">
          <div>
            <h2 className="modal-title">批量编辑商品</h2>
            <p className="text-xs text-slate-500 mt-1">账号 {accountId || '未选择'} · 已选 {items.length} 件</p>
          </div>
          <button type="button" className="modal-close" title="关闭" onClick={onClose}><X className="w-5 h-5" /></button>
        </div>
        <div className="modal-body overflow-y-auto space-y-4">
          {invalidReason && (
            <div className="flex items-center gap-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
              <AlertCircle className="h-4 w-4 shrink-0" />{invalidReason}
            </div>
          )}
          {!detail && (
            <>
              <div className="rounded border border-slate-200 p-3 text-xs text-slate-500">
                仅修改填写的字段；图片留空表示保留每个商品现有图片，填写图片地址会替换所有目标图片。
              </div>
              <label className="input-group"><span className="input-label">标题（可选）</span><input className="input-ios" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} /></label>
              <label className="input-group"><span className="input-label">描述（可选）</span><textarea className="input-ios min-h-28 resize-y" value={description} onChange={(event) => setDescription(event.target.value)} maxLength={5000} /></label>
              <label className="input-group"><span className="input-label">价格（可选）</span><input className="input-ios" inputMode="decimal" value={price} onChange={(event) => setPrice(event.target.value)} placeholder="例如 29.90" /></label>
              <label className="input-group"><span className="input-label">图片地址（可选，每行或逗号分隔）</span><textarea className="input-ios min-h-20 resize-y" value={images} onChange={(event) => setImages(event.target.value)} placeholder="留空则保留各商品图片" /></label>
              <label className="input-group"><span className="input-label">执行时间窗口（必选）</span><select className="input-ios" value={windowHours} onChange={(event) => setWindowHours(event.target.value ? Number(event.target.value) as WindowHours : '')}><option value="">请选择 1 / 3 / 5 / 12 / 24 小时</option>{WINDOW_OPTIONS.map((value) => <option key={value} value={value}>{value} 小时</option>)}</select></label>
            </>
          )}
          {detail && (
            <div className="space-y-3">
              <div className="flex items-center justify-between rounded border border-slate-200 p-3">
                <div><div className="font-medium">任务 {detail.batch_id}</div><div className="text-xs text-slate-500">窗口 {detail.window_hours} 小时 · 截止 {formatTime(detail.deadline_at)}</div></div>
                <button type="button" className="btn-ios-secondary btn-sm" onClick={() => refreshStatus()} disabled={refreshing}><RefreshCw className={refreshing ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />刷新状态</button>
              </div>
              <div className="space-y-2">
                {(detail.targets || []).map((target) => (
                  <div key={target.id} className="rounded border border-slate-200 p-3 text-sm">
                    <div className="flex items-center justify-between gap-2"><span>商品 {target.item_id}</span><span className="inline-flex items-center gap-1">{target.status === 'success' ? <CheckCircle2 className="h-4 w-4 text-emerald-600" /> : target.status === 'unknown' ? <AlertCircle className="h-4 w-4 text-amber-600" /> : <Clock3 className="h-4 w-4 text-slate-400" />}{STATUS_LABELS[target.status] || target.status}</span></div>
                    <div className="mt-1 text-xs text-slate-500">计划 {formatTime(target.scheduled_at)} · 请求 {formatTime(target.request_started_at)} · 完成 {formatTime(target.finished_at)}</div>
                    {target.message && <div className="mt-1 text-xs text-red-600">{target.message}</div>}
                  </div>
                ))}
              </div>
              {failedTargets.length > 0 && (
                <div className="rounded border border-red-200 bg-red-50 p-3">
                  <div className="text-sm font-medium text-red-700">仅明确失败项可重试（结果未知项需先核对平台）</div>
                  <div className="mt-2 flex items-center gap-2"><select className="input-ios" value={retryWindow} onChange={(event) => setRetryWindow(event.target.value ? Number(event.target.value) as WindowHours : '')}><option value="">请选择新的时间窗口</option>{WINDOW_OPTIONS.map((value) => <option key={value} value={value}>{value} 小时</option>)}</select><button type="button" className="btn-ios-primary btn-sm" onClick={handleRetry} disabled={retrying || !retryWindow}><Loader2 className={retrying ? 'h-4 w-4 animate-spin' : 'h-4 w-4'} />重试失败项</button></div>
                </div>
              )}
            </div>
          )}
        </div>
        {!detail && <div className="modal-footer flex justify-end gap-2"><button type="button" className="btn-ios-secondary" onClick={onClose} disabled={loading}>取消</button><button type="button" className="btn-ios-primary" onClick={handleCreate} disabled={loading || Boolean(invalidReason)}>{loading && <Loader2 className="h-4 w-4 animate-spin" />}创建批量编辑任务</button></div>}
      </div>
    </div>
  )
}