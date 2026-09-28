/**
 * 批量发布页面
 *
 * 功能：
 * 1. 选择多个闲鱼账号
 * 2. 从素材库选择多条素材
 * 3. 提交批量发布任务（后台异步执行）
 * 4. 轮询任务进度，展示完成状态
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import { motion } from 'framer-motion'
import { Layers, CheckCircle, XCircle, Clock, Play, Loader2 } from 'lucide-react'
import { useUIStore } from '@/store/uiStore'
import { publishBatch, getBatchStatus, getMaterials, type ProductMaterial, type BatchAccountStatus } from '@/api/productPublish'
import { getAccountDetails, updateAccountPublishCapacity, getAccountPublishReservations, resolveAccountPublishReservation, type PublishCapacityReservation } from '@/api/accounts'

interface BatchProgress {
  batch_id: string
  total: number
  success: number
  failed: number
  unknown: number
  skipped: number
  publishing: number
  pending: number
  finished: boolean
  snapshot_available: boolean
  account_statuses: BatchAccountStatus[]
}

// sessionStorage 键名：保存进行中的 batch_id
const BATCH_ID_STORAGE_KEY = 'batch_publish_active_batch_id'

export function BatchPublish() {
  const { addToast } = useUIStore()
  const [accounts, setAccounts] = useState<any[]>([])
  const [capacityDraft, setCapacityDraft] = useState<Record<string, string>>({})
  const [savingCapacity, setSavingCapacity] = useState<string | null>(null)
  const [reservationAccount, setReservationAccount] = useState<string | null>(null)
  const [reservations, setReservations] = useState<PublishCapacityReservation[]>([])
  const [reconcileItemIds, setReconcileItemIds] = useState<Record<string, string>>({})
  const [reconciling, setReconciling] = useState<string | null>(null)
  const [materials, setMaterials] = useState<ProductMaterial[]>([])
  const [selectedAccounts, setSelectedAccounts] = useState<Set<string>>(new Set())
  const [selectedMaterials, setSelectedMaterials] = useState<Set<number>>(new Set())
  const [loadingAccounts, setLoadingAccounts] = useState(true)
  const [loadingMaterials, setLoadingMaterials] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [progress, setProgress] = useState<BatchProgress | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const [materialSearch, setMaterialSearch] = useState('')
  const accountNameMap = new Map(accounts.map((account: any) => [account.id, account.note || account.id]))

  const getSyncStatusLabel = (status: BatchAccountStatus['sync_status']) => {
    if (status === 'success') return '已成功'
    if (status === 'failed') return '失败'
    if (status === 'running') return '获取中'
    if (status === 'skipped') return '未触发'
    if (status === 'unknown') return '状态未知'
    return '待执行'
  }

  const getSyncStatusClassName = (status: BatchAccountStatus['sync_status']) => {
    if (status === 'success') return 'badge-success'
    if (status === 'failed') return 'badge-danger'
    if (status === 'running') return 'badge-info'
    if (status === 'skipped') return 'badge-warning'
    if (status === 'unknown') return 'badge-warning'
    return 'badge-secondary'
  }

  /** 清除 sessionStorage 中的 batch_id */
  const clearStoredBatchId = useCallback(() => {
    try { sessionStorage.removeItem(BATCH_ID_STORAGE_KEY) } catch { /* ignore */ }
  }, [])

  /** 保存 batch_id 到 sessionStorage */
  const storeBatchId = useCallback((batchId: string) => {
    try { sessionStorage.setItem(BATCH_ID_STORAGE_KEY, batchId) } catch { /* ignore */ }
  }, [])

  /** 启动轮询批量发布进度 */
  const startPolling = useCallback((batchId: string) => {
    // 避免重复启动
    if (pollingRef.current) clearInterval(pollingRef.current)
    pollingRef.current = setInterval(async () => {
      try {
        const res = await getBatchStatus(batchId)
        if (res.success) {
          setProgress(res.data)
          if (!res.data.snapshot_available) {
            if (pollingRef.current) clearInterval(pollingRef.current)
            clearStoredBatchId()
            addToast({ type: 'warning', message: res.message || '仅有部分发布日志，无法确认批次完成状态' })
            return
          }
          if (res.data.finished) {
            if (pollingRef.current) clearInterval(pollingRef.current)
            getAccountDetails().then(setAccounts).catch(() => {})
            const syncFailedCount = res.data.account_statuses.filter(item => item.sync_status === 'failed').length
            const syncUnknownCount = res.data.account_statuses.filter(item => item.sync_status === 'unknown').length
            const syncProblemCount = syncFailedCount + syncUnknownCount
            addToast({
              type: res.data.failed === 0 && res.data.unknown === 0 && res.data.skipped === 0 && syncProblemCount === 0 ? 'success' : 'warning',
              message: syncFailedCount > 0
                ? `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条，跳过 ${res.data.skipped} 条，结果未知 ${res.data.unknown} 条，${syncFailedCount} 个账号自动获取商品失败`
                : syncUnknownCount > 0
                  ? `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条，跳过 ${res.data.skipped} 条，结果未知 ${res.data.unknown} 条，${syncUnknownCount} 个账号自动获取商品状态未知`
                  : `批量发布完成！成功 ${res.data.success} 条，失败 ${res.data.failed} 条，跳过 ${res.data.skipped} 条，结果未知 ${res.data.unknown} 条`,
            })
          }
        } else {
          if (pollingRef.current) clearInterval(pollingRef.current)
          setProgress(null)
          addToast({ type: 'warning', message: res.message || '批量任务状态已失效，请重新提交任务' })
        }
      } catch { /* 静默处理轮询错误 */ }
    }, 3000)
  }, [addToast, clearStoredBatchId])

  useEffect(() => {
    getAccountDetails()
      .then(list => { setAccounts(list); setLoadingAccounts(false) })
      .catch(() => { setLoadingAccounts(false) })
    getMaterials(1, 1000)
      .then(res => { if (res.success) setMaterials(res.data.list); setLoadingMaterials(false) })
      .catch(() => { setLoadingMaterials(false) })

    // 恢复未完成的批量发布任务轮询
    try {
      const savedBatchId = sessionStorage.getItem(BATCH_ID_STORAGE_KEY)
      if (savedBatchId) {
        // 先查询一次状态，确认任务仍有效后再启动轮询
        getBatchStatus(savedBatchId).then(res => {
          if (res.success && !res.data.snapshot_available) {
            setProgress(res.data)
            clearStoredBatchId()
          } else if (res.success && !res.data.finished) {
            setProgress(res.data)
            startPolling(savedBatchId)
          } else if (res.success && res.data.finished) {
            // 任务已完成，显示最终状态
            setProgress(res.data)
          } else {
            // 任务已失效，清除缓存以便提交新任务
            clearStoredBatchId()
          }
        }).catch(() => { /* 查询失败，保留缓存下次再试 */ })
      }
    } catch { /* ignore */ }

    return () => { if (pollingRef.current) clearInterval(pollingRef.current) }
  }, [startPolling, clearStoredBatchId])

  const saveCapacity = async (accountId: string) => {
    const raw = capacityDraft[accountId]
    if (raw === undefined || !/^(0|[1-9]\d*)$/.test(raw)) {
      addToast({ type: 'warning', message: '请输入非负整数的剩余可发布数量' })
      return
    }
    const remaining = Number(raw)
    if (!Number.isSafeInteger(remaining)) {
      addToast({ type: 'warning', message: '剩余可发布数量超出允许范围' })
      return
    }
    setSavingCapacity(accountId)
    try {
      const result = await updateAccountPublishCapacity(accountId, remaining)
      if (!result.success || !result.data) throw new Error(result.message || '保存失败')
      const capacity = result.data
      setAccounts(previous => previous.map(account => account.id === accountId
        ? { ...account, remaining_publish_capacity: capacity.remaining_publish_capacity, reserved_publish_count: capacity.reserved_publish_count }
        : account))
      addToast({ type: 'success', message: '剩余可发布数量已保存' })
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '保存失败' })
    } finally {
      setSavingCapacity(null)
    }
  }

  const openReservations = async (accountId: string) => {
    if (reservationAccount === accountId) {
      setReservationAccount(null)
      return
    }
    try {
      const response = await getAccountPublishReservations(accountId)
      if (!response.success) throw new Error(response.message || '查询失败')
      setReservations(response.data || [])
      setReservationAccount(accountId)
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '查询失败' })
    }
  }

  const reconcileReservation = async (accountId: string, reservationId: string, outcome: 'success' | 'failed') => {
    const itemId = (reconcileItemIds[reservationId] ?? reservations.find(item => item.id === reservationId)?.item_id ?? '').trim()
    if (outcome === 'success' && !itemId) {
      addToast({ type: 'warning', message: '确认发布成功时请填写平台商品 ID' })
      return
    }
    const confirmation = outcome === 'success'
      ? '请确认已在闲鱼核实该商品发布成功。此操作会扣减 1 个发布额度。'
      : '请确认已在闲鱼核实该商品未发布。此操作会释放 1 个预留额度。'
    if (!window.confirm(confirmation)) return
    setReconciling(reservationId)
    try {
      const response = await resolveAccountPublishReservation(accountId, reservationId, outcome, itemId)
      if (!response.success) throw new Error(response.message || '对账失败')
      const [reservationResponse, accountList] = await Promise.all([
        getAccountPublishReservations(accountId), getAccountDetails(),
      ])
      setReservations(reservationResponse.data || [])
      setAccounts(accountList)
      addToast({ type: 'success', message: '对账结果已保存' })
    } catch (error) {
      addToast({ type: 'error', message: error instanceof Error ? error.message : '对账失败' })
    } finally {
      setReconciling(null)
    }
  }

  /** 提交批量发布任务 */
  const handleSubmit = async () => {
    if (selectedAccounts.size === 0) { addToast({ type: 'warning', message: '请至少选择一个账号' }); return }
    if (selectedMaterials.size === 0) { addToast({ type: 'warning', message: '请至少选择一条素材' }); return }
    setSubmitting(true)
    try {
      const res = await publishBatch({
        account_ids: Array.from(selectedAccounts),
        material_ids: Array.from(selectedMaterials),
      })
      if (res.success) {
        addToast({ type: 'success', message: res.message || '批量发布任务已提交' })
        const batchId = res.data?.batch_id
        const totalCount = res.data?.total ?? 0
        const accountCount = selectedAccounts.size
        const materialCountPerAccount = accountCount > 0 ? Math.floor(totalCount / accountCount) : 0
        if (batchId) {
          storeBatchId(batchId)
          setProgress({
            batch_id: batchId,
            total: totalCount,
            success: 0,
            failed: 0,
            unknown: 0,
            skipped: 0,
            publishing: 0,
            pending: totalCount,
            finished: false,
            snapshot_available: true,
            account_statuses: Array.from(selectedAccounts).map(accountId => ({
              account_id: accountId,
              total: materialCountPerAccount,
              success: 0,
              failed: 0,
              unknown: 0,
              skipped: 0,
              publishing: 0,
              pending: materialCountPerAccount,
              sync_status: 'pending',
              sync_message: '等待该账号发布完成后自动获取商品',
              sync_total_count: 0,
              sync_saved_count: 0,
            })),
          })
          startPolling(batchId)
        }
      } else {
        addToast({ type: 'error', message: res.message || '提交失败' })
      }
    } catch {
      addToast({ type: 'error', message: '网络错误，请重试' })
    } finally {
      setSubmitting(false)
    }
  }

  const toggleAccount = (id: string) => setSelectedAccounts(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleMaterial = (id: number) => setSelectedMaterials(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAllAccounts = () => selectedAccounts.size === accounts.length ? setSelectedAccounts(new Set()) : setSelectedAccounts(new Set(accounts.map((a: any) => a.id)))
  const toggleAllMaterials = () => {
    const ids = filteredMaterials.map(m => m.id)
    const allSelected = ids.length > 0 && ids.every(id => selectedMaterials.has(id))
    if (allSelected) {
      setSelectedMaterials(prev => { const n = new Set(prev); ids.forEach(id => n.delete(id)); return n })
    } else {
      setSelectedMaterials(prev => { const n = new Set(prev); ids.forEach(id => n.add(id)); return n })
    }
  }

  const filteredMaterials = materialSearch.trim()
    ? materials.filter(m => m.title.toLowerCase().includes(materialSearch.trim().toLowerCase()))
    : materials

  const total = selectedAccounts.size * selectedMaterials.size
  const isDisabled = submitting || total === 0 || (progress !== null && !progress.finished)

  return (
    <div className="space-y-3 sm:space-y-4">
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="page-title">批量发布</h1>
          <p className="page-description">多账号  多素材并发发布，提升发布效率</p>
          <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
            批量发布时会忽略素材库中填写的宝贝所在地，统一从随机地址库自动分配地址。
          </p>
        </div>
        <div className="text-sm text-slate-500 bg-slate-100 dark:bg-slate-800 px-3 py-1.5 rounded-lg">
          {selectedAccounts.size} 账号  {selectedMaterials.size} 素材 =&nbsp;
          <span className="font-semibold text-blue-600 dark:text-blue-400">{total} 次发布</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 账号选择 */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title">选择账号</h2>
            <button className="text-sm text-blue-500 hover:underline" onClick={toggleAllAccounts}>
              {selectedAccounts.size === accounts.length && accounts.length > 0 ? '取消全选' : '全选'}
            </button>
          </div>
          <div className="vben-card-body">
            {loadingAccounts ? (
              <div className="flex justify-center py-8"><Loader2 className="w-8 h-8 animate-spin text-blue-500" /></div>
            ) : accounts.length === 0 ? (
              <p className="text-center text-slate-400 py-8">暂无账号，请先添加账号</p>
            ) : (
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {accounts.map((a: any) => {
                  const checked = selectedAccounts.has(a.id)
                  const enabled = a.enabled !== false
                  return (
                    <div key={a.id} className={`p-2.5 rounded-lg ${checked ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-700'}`}>
                      <label className="flex items-center gap-3 cursor-pointer">
                        <input type="checkbox" className="w-4 h-4 text-blue-600 rounded accent-blue-500"
                          checked={checked} onChange={() => toggleAccount(a.id)} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium truncate text-slate-800 dark:text-slate-100">{a.note || a.id}</p>
                          {a.note && <p className="text-xs text-slate-400 truncate">{a.id}</p>}
                        </div>
                        <span className={`${enabled ? 'badge-success' : 'badge-secondary'} flex-shrink-0`}>{enabled ? '已启动' : '未启动'}</span>
                      </label>
                      <div className="mt-2 ml-7 flex items-center gap-2 text-xs">
                        <span className="text-slate-500 whitespace-nowrap">剩余额度</span>
                        <input type="number" min="0" step="1" className="input-ios w-24 py-1"
                          aria-label={`${a.id} 剩余可发布数量`}
                          placeholder={a.remaining_publish_capacity == null ? '未设置' : String(a.remaining_publish_capacity)}
                          value={capacityDraft[a.id] ?? (a.remaining_publish_capacity == null ? '' : String(a.remaining_publish_capacity))}
                          onChange={event => setCapacityDraft(previous => ({ ...previous, [a.id]: event.target.value }))} />
                        <button type="button" className="text-blue-600 whitespace-nowrap disabled:opacity-50"
                          disabled={savingCapacity === a.id || capacityDraft[a.id] === undefined}
                          onClick={() => saveCapacity(a.id)}>保存</button>
                        {a.remaining_publish_capacity != null && <span className="text-slate-500">可用 {Math.max(0, a.remaining_publish_capacity - (a.reserved_publish_count || 0))}</span>}
                        {(a.reserved_publish_count || 0) > 0 && <button type="button" className="text-amber-600 whitespace-nowrap" onClick={() => openReservations(a.id)}>预留 {a.reserved_publish_count} · 对账</button>}
                      </div>
                      {reservationAccount === a.id && <div className="mt-2 ml-7 space-y-2 text-xs">
                        <p className="text-amber-700">请先在闲鱼核实平台商品，再记录结果。正在执行的发布不能对账。</p>
                        {reservations.length === 0 && <p className="text-slate-500">暂无未结算发布</p>}
                        {reservations.map(reservation => <div key={reservation.id} className="rounded border border-slate-200 dark:border-slate-700 p-2 space-y-1">
                          <p>日志 #{reservation.publish_log_id} · {reservation.status === 'unknown' ? '结果未知' : '发布中或待检查'}</p>
                          {reservation.item_id && <p>平台商品 ID：{reservation.item_id}</p>}
                          {reservation.status === 'unknown' && <div className="flex flex-wrap items-center gap-2">
                            <input className="input-ios w-36 py-1" aria-label="确认成功的平台商品 ID" placeholder="平台商品 ID"
                              value={reconcileItemIds[reservation.id] ?? reservation.item_id ?? ''}
                              onChange={event => setReconcileItemIds(previous => ({ ...previous, [reservation.id]: event.target.value }))} />
                            <button type="button" className="text-emerald-600 disabled:opacity-50" disabled={reconciling === reservation.id}
                              onClick={() => reconcileReservation(a.id, reservation.id, 'success')}>确认已发布</button>
                            <button type="button" className="text-amber-600 disabled:opacity-50" disabled={reconciling === reservation.id}
                              onClick={() => reconcileReservation(a.id, reservation.id, 'failed')}>确认未发布</button>
                          </div>}
                        </div>)}
                      </div>}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </motion.div>

        {/* 素材选择 */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title">选择素材</h2>
            <button className="text-sm text-blue-500 hover:underline" onClick={toggleAllMaterials}>
              {selectedMaterials.size === filteredMaterials.length && filteredMaterials.length > 0 ? '取消全选' : '全选'}
            </button>
          </div>
          <div className="vben-card-body">
            <input
              className="input-ios w-full mb-2"
              placeholder="搜索素材标题..."
              value={materialSearch}
              onChange={e => setMaterialSearch(e.target.value)}
            />
            {loadingMaterials ? (
              <div className="flex justify-center py-8"><Loader2 className="w-8 h-8 animate-spin text-blue-500" /></div>
            ) : filteredMaterials.length === 0 ? (
              <p className="text-center text-slate-400 py-8">{materials.length === 0 ? '素材库为空，请先在「素材库」页面添加素材' : '没有匹配的素材'}</p>
            ) : (
              <div className="space-y-1 max-h-72 overflow-y-auto">
                {filteredMaterials.map(m => {
                  const checked = selectedMaterials.has(m.id)
                  const specificationCount = (m.specifications || []).length
                  const skuCount = (m.sku_rows || []).length
                  const isMultiSpec = specificationCount > 0 || skuCount > 0
                  return (
                    <label key={m.id} className={`flex items-center gap-3 p-2.5 rounded-lg cursor-pointer transition-colors ${checked ? 'bg-blue-50 dark:bg-blue-900/20' : 'hover:bg-slate-50 dark:hover:bg-slate-700'}`}>
                      <input type="checkbox" className="w-4 h-4 text-blue-600 rounded accent-blue-500"
                        checked={checked} onChange={() => toggleMaterial(m.id)} />
                      {m.images?.[0] ? (
                        <img src={m.images[0]} alt={m.title} className="w-10 h-10 object-cover rounded-lg flex-shrink-0" />
                      ) : (
                        <div className="w-10 h-10 bg-slate-100 dark:bg-slate-700 rounded-lg flex items-center justify-center text-xs text-slate-400 flex-shrink-0">无图</div>
                      )}
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate text-slate-800 dark:text-slate-100">{m.title}</p>
                        <div className="mt-1 flex flex-wrap items-center gap-1.5">
                          <span className="text-xs text-amber-600">{m.price}</span>
                          {isMultiSpec ? (
                            <span className="badge-info flex-shrink-0">多规格 · {specificationCount}类 / {skuCount}组合</span>
                          ) : (
                            <span className="badge-secondary flex-shrink-0">单规格</span>
                          )}
                        </div>
                      </div>
                    </label>
                  )
                })}
              </div>
            )}
          </div>
        </motion.div>
      </div>

      {/* 提交按钮 */}
      <div className="flex justify-center">
        <button className="btn-ios-primary min-w-48" disabled={isDisabled} onClick={handleSubmit}>
          {submitting
            ? <><Loader2 className="w-4 h-4 animate-spin" />提交中...</>
            : <><Play className="w-4 h-4" />开始批量发布（{total} 次）</>}
        </button>
      </div>

      {/* 进度面板 */}
      {progress && (
        <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="vben-card">
          <div className="vben-card-header">
            <h2 className="vben-card-title"><Layers className="w-4 h-4" />发布进度</h2>
            {!progress.snapshot_available
              ? <span className="badge-warning">状态不完整</span>
              : progress.finished
                ? <span className="badge-success">已完成</span>
                : <Loader2 className="w-4 h-4 animate-spin text-blue-500" />}
          </div>
          <div className="vben-card-body">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mb-4">
              {[
                { label: '总数', value: progress.total, icon: <Layers className="w-5 h-5" />, cls: 'stat-icon-primary' },
                { label: '成功', value: progress.success, icon: <CheckCircle className="w-5 h-5" />, cls: 'stat-icon-success' },
                { label: '失败', value: progress.failed, icon: <XCircle className="w-5 h-5" />, cls: 'stat-icon-warning' },
                { label: '结果未知', value: progress.unknown, icon: <Clock className="w-5 h-5" />, cls: 'stat-icon-warning' },
                { label: '跳过', value: progress.skipped, icon: <Clock className="w-5 h-5" />, cls: 'stat-icon-warning' },
                { label: '进行中', value: progress.publishing + progress.pending, icon: <Clock className="w-5 h-5" />, cls: 'stat-icon-info' },
              ].map(item => (
                <div key={item.label} className="stat-card">
                  <div className={item.cls}>{item.icon}</div>
                  <div>
                    <div className="stat-value">{item.value}</div>
                    <div className="stat-label">{item.label}</div>
                  </div>
                </div>
              ))}
            </div>
            {progress.total > 0 && (
              <>
                <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-2 mb-1">
                  <div className="bg-blue-500 h-2 rounded-full transition-all duration-500"
                    style={{ width: `${Math.round((progress.success + progress.failed + progress.unknown + progress.skipped) / progress.total * 100)}%` }} />
                </div>
                <div className="flex justify-between text-xs text-slate-400">
                  <span>进度 {Math.round((progress.success + progress.failed + progress.unknown + progress.skipped) / progress.total * 100)}%</span>
                  <span>批次 ID：{progress.batch_id.slice(0, 8)}...</span>
                </div>
              </>
            )}
            {!progress.snapshot_available && <p className="text-xs text-amber-600 mt-2">仅恢复了已写入的发布日志，无法确认是否还有未执行项；请先对账。</p>}
            {progress.snapshot_available && !progress.finished && <p className="text-xs text-slate-400 mt-2">每 3 秒自动刷新进度</p>}
            {progress.account_statuses.length > 0 && (
              <div className="mt-4 border-t border-slate-200 dark:border-slate-700 pt-4">
                <div className="flex items-center justify-between gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">账号自动获取商品状态</h3>
                  <span className="text-xs text-slate-400">按账号展示发布后商品同步结果</span>
                </div>
                <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                  {progress.account_statuses.map(accountStatus => (
                    <div key={accountStatus.account_id} className="rounded-xl border border-slate-200 dark:border-slate-700 p-3 bg-slate-50/80 dark:bg-slate-800/60">
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
                        <div className="min-w-0">
                          <div className="text-sm font-medium text-slate-800 dark:text-slate-100 truncate">
                            {accountNameMap.get(accountStatus.account_id) || accountStatus.account_id}
                          </div>
                          <div className="text-xs text-slate-400 truncate">账号ID：{accountStatus.account_id}</div>
                        </div>
                        <span className={getSyncStatusClassName(accountStatus.sync_status)}>{getSyncStatusLabel(accountStatus.sync_status)}</span>
                      </div>
                      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mt-3 text-xs">
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布总数</div>
                          <div className="mt-1 font-semibold text-slate-700 dark:text-slate-100">{accountStatus.total}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布成功</div>
                          <div className="mt-1 font-semibold text-emerald-600">{accountStatus.success}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">发布失败</div>
                          <div className="mt-1 font-semibold text-amber-600">{accountStatus.failed}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">结果未知</div>
                          <div className="mt-1 font-semibold text-amber-600">{accountStatus.unknown}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">跳过</div>
                          <div className="mt-1 font-semibold text-slate-600">{accountStatus.skipped}</div>
                        </div>
                        <div className="rounded-lg bg-white dark:bg-slate-900 px-2.5 py-2">
                          <div className="text-slate-400">待处理</div>
                          <div className="mt-1 font-semibold text-blue-600">{accountStatus.publishing + accountStatus.pending}</div>
                        </div>
                      </div>
                      <div className="mt-3 text-xs text-slate-500 dark:text-slate-300 break-all">{accountStatus.sync_message}</div>
                      {(accountStatus.sync_status === 'success' || accountStatus.sync_total_count > 0 || accountStatus.sync_saved_count > 0) && (
                        <div className="mt-2 text-xs text-slate-500 dark:text-slate-300">
                          已抓取 {accountStatus.sync_total_count} 件，入库 {accountStatus.sync_saved_count} 件
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </div>
  )
}

export default BatchPublish
