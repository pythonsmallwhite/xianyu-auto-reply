import { useEffect, useRef, useState } from 'react'
import { get, post } from '@/utils/request'

type Listing = { id: number; account_id: string; item_id: string; state: string }
type Product = { id: number; title: string; listings: Listing[] }
type Target = { id: number; account_id: string; item_id: string; status: string; scheduled_at: string; request_started_at?: string; message?: string; schedule_error?: string; retry_batch_id?: string; reconciled_state?: string; reconciled_note?: string; reconciled_at?: string }
type Detail = { id: string; window_hours: number; deadline_at: string; finished: boolean; targets: Target[]; attempts: {id: number; target_id: number; status: string; message?: string}[] }
type Response<T> = {success: boolean; data: T; message?: string}
const root = '/api/v1/internal-products'
const labels: Record<string, string> = {pending:'待执行', running:'执行中', success:'成功', failed:'明确失败', unknown:'结果未知', deferred:'等待间隔', reconciled:'已人工核对'}
type Reconcile = { batchId: string; targetId: number; state: 'offline' | 'active'; note: string }
type Confirmation = { mode: 'create' | 'retry'; productId: string; batchId: string; title: string; hours: string; targets: (Listing | Target)[] }
async function read<T>(url: string) {
  const res = await get<Response<T>>(url)
  if (!res.success) throw new Error(res.message || '查询失败')
  return res.data
}

export function OfflineBatches() {
  const [products, setProducts] = useState<Product[]>([])
  const [productId, setProductId] = useState('')
  const [selected, setSelected] = useState<number[]>([])
  const [windowHours, setWindowHours] = useState('')
  const [history, setHistory] = useState<{batch_id: string}[]>([])
  const [batchId, setBatchId] = useState('')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<Confirmation | null>(null)
  const [reconcile, setReconcile] = useState<Reconcile | null>(null)
  const request = useRef<{key: string; id: string} | null>(null)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const [notice, setNotice] = useState('')
  const [detailError, setDetailError] = useState('')
  const [saving, setSaving] = useState(false)
  const savingRef = useRef(false)
  const detailGeneration = useRef(0)
  const contextGeneration = useRef(0)
  const product = products.find(p => String(p.id) === productId)
  const failed = detail?.targets.filter(t => t.status === 'failed' && !t.retry_batch_id) || []
  const unknown = detail?.targets.filter(t => t.status === 'unknown') || []
  const locked = busy || !!confirm || !!reconcile
  useEffect(() => { let live = true; read<Product[]>(root).then(r => {if(live) setProducts(r)}).catch(e => {if(live) setError(e.message)}); return () => {live = false} }, [])
  useEffect(() => {
    let live = true
    contextGeneration.current++; detailGeneration.current++
    setSelected([]); setDetail(null); setBatchId(''); setHistory([]); setWindowHours(''); setConfirm(null); setReconcile(null); setNotice(''); setError(''); setDetailError('')
    if (productId) read<{batch_id: string}[]>(`${root}/${productId}/offline-batches`).then(r => {if(live) setHistory(r)}).catch(e => {if(live) setError(e.message)})
    return () => {live = false}
  }, [productId])
  useEffect(() => {
    contextGeneration.current++
    setDetail(null); setReconcile(null); setNotice(''); setError(''); setDetailError('')
    return () => {contextGeneration.current++}
  }, [productId, batchId])
  useEffect(() => {
    let live = true; let timer: ReturnType<typeof setTimeout>
    setDetailError('')
    const refresh = async () => {
      if(savingRef.current) return
      const generation = ++detailGeneration.current
      try { const value = await read<Detail>(`${root}/offline-batches/${batchId}`); if(live && !savingRef.current && generation === detailGeneration.current) {
        setDetail(value); setDetailError('')
        setReconcile(prev => prev && !value.targets.some(t => t.id === prev.targetId && t.status === 'unknown') ? null : prev)
        if(!value.finished) timer = setTimeout(refresh, 3000)
      } }
      catch(e) {if(live && !savingRef.current && generation === detailGeneration.current) setDetailError(`详情刷新失败：${e instanceof Error ? e.message : '状态读取失败'}`)}
    }
    if(batchId && !saving) void refresh()
    return () => {live = false; detailGeneration.current++; clearTimeout(timer)}
  }, [productId, batchId, refreshVersion, saving])
  const openConfirm = (mode: 'create' | 'retry') => {
    if(!product || !windowHours || locked) return
    const targets = mode === 'create' ? product.listings.filter(l => selected.includes(l.id) && l.state === 'active') : failed
    if(targets.length) setConfirm({mode, productId, batchId, title: product.title, hours: windowHours, targets})
  }
  const submit = async () => {
    if(!confirm || !product || !confirm.hours || busy) return
    const generation = contextGeneration.current
    const {mode, targets, hours} = confirm
    if(confirm.productId !== productId || confirm.batchId !== batchId || !targets.length || targets.some(t => mode === 'retry' ? detail?.id !== batchId || !failed.some(current => current.id === t.id) : !product.listings.some(current => current.id === t.id && current.state === 'active'))) {
      setError('确认范围已失效，请重新确认'); setConfirm(null); return
    }
    const ids = targets.map(t => t.id)
    const key = JSON.stringify([mode, productId, batchId, ids, hours])
    if(request.current?.key !== key) request.current = {key, id:crypto.randomUUID()}
    setBusy(true); setError('')
    try {
      const url = mode === 'create' ? `${root}/${productId}/offline-batches` : `${root}/offline-batches/${batchId}/retry`
      const res = await post<Response<{batch_id: string}>>(url, {
        [mode === 'create' ? 'listing_ids' : 'target_ids']:ids, window_hours:Number(hours), request_id:request.current.id, confirmed:true,
      })
      if(generation !== contextGeneration.current) return
      if(!res.success) throw new Error(res.message || '创建失败')
      setHistory(prev => [{batch_id:res.data.batch_id}, ...prev.filter(b => b.batch_id !== res.data.batch_id)])
      setBatchId(res.data.batch_id); setConfirm(null); setSelected([]); setWindowHours(''); request.current=null
    } catch(e) {if(generation === contextGeneration.current) setError(e instanceof Error ? e.message : '请求失败；重试将沿用请求 ID')}
    finally {setBusy(false)}
  }
  // 核对只提交真实平台状态，不重发请求；结论本身即为记录，故不需要请求 ID。
  const verify = async () => {
    if(!reconcile || busy || !reconcile.note.trim() || reconcile.batchId !== batchId || detail?.id !== batchId || !detail.targets.some(t => t.id === reconcile.targetId && t.status === 'unknown')) return
    const { targetId, state, note } = reconcile
    const generation = contextGeneration.current
    detailGeneration.current++
    savingRef.current = true; setSaving(true)
    setBusy(true); setError(''); setNotice('')
    let rejected = false
    try {
      const res = await post<Response<{status: string; conflict: boolean; message?: string}>>(
        `${root}/offline-batches/${batchId}/targets/${targetId}/reconcile`,
        { platform_state: state, note: note.trim(), confirmed: true },
      )
      if(generation !== contextGeneration.current) return
      if(!res.success) {rejected = true; throw new Error(res.message || '核对失败')}
      setReconcile(null); setDetail(null)
      setNotice(`核对结论已保存，无需重新提交。${res.data.conflict ? res.data.message || '平台已下架，但本地状态已变更，请同步核对' : ''}`)
    } catch(e) {if(generation === contextGeneration.current) setError(`${rejected ? '核对未保存' : '保存结果未确认，请先取消核对并刷新详情，不要直接重发结论'}：${e instanceof Error ? e.message : '请求失败'}`)}
    finally {savingRef.current = false; setSaving(false); setBusy(false); if(generation === contextGeneration.current) setRefreshVersion(v => v + 1)}
  }
  return <details className="vben-card p-4">
    <summary className="cursor-pointer font-medium">关联商品延迟下架</summary>
    <div className="space-y-3 mt-3">
      <p className="text-sm">仅操作明确关联商品；历史商品仍用原有单件下架。恢复功能暂未接入。</p>
      {notice && <p role="status" className="text-amber-700">{notice}</p>}
      {error && <p role="alert" className="text-red-600">{error}</p>}
      {detailError && <p role="alert" className="text-red-600">{detailError}</p>}
      <select className="input-ios" disabled={locked} value={productId} onChange={e => setProductId(e.target.value)}>
        <option value="">选择内部商品</option>{products.map(p => <option key={p.id} value={p.id}>{p.title}</option>)}
      </select>
      {product && <fieldset disabled={locked} className="space-y-1">
        <button type="button" className="btn-ios-secondary" onClick={() => setSelected(product.listings.filter(l => l.state === 'active').map(l => l.id))}>选择全部在售关联项</button>
        {product.listings.map(l => <label key={l.id} className="flex gap-2"><input type="checkbox" disabled={l.state !== 'active'} checked={selected.includes(l.id)} onChange={e => setSelected(prev => e.target.checked ? [...prev,l.id] : prev.filter(id => id !== l.id))}/>账号 {l.account_id} · 商品 {l.item_id} · {l.state}</label>)}
      </fieldset>}
      <select className="input-ios" disabled={locked} value={windowHours} onChange={e => setWindowHours(e.target.value)}>
        <option value="">请选择本次窗口（重试需重新选择）</option>{[1,3,5,12,24].map(h => <option key={h} value={h}>{h} 小时</option>)}
      </select>
      <button className="btn-ios-primary" disabled={locked || !selected.length || !windowHours} onClick={() => openConfirm('create')}>确认下架范围</button>
      <select className="input-ios" disabled={locked} value={batchId} onChange={e => {setBatchId(e.target.value); setWindowHours(''); setReconcile(null)}}>
        <option value="">查看最近 50 个任务</option>{history.map(b => <option key={b.batch_id}>{b.batch_id}</option>)}
      </select>
      {batchId && <button className="btn-ios-secondary" disabled={locked} onClick={() => setRefreshVersion(v => v + 1)}>刷新任务详情</button>}
      {detail && <div className="space-y-2">
        {!!unknown.length && <p role="alert" className="text-amber-700">有 {unknown.length} 个结果未知项需要人工核对；核对完成前不能为同一商品另建任务，也不会自动重发。</p>}
        <p>窗口 {detail.window_hours} 小时 · 截止 {detail.deadline_at}（北京时间）</p>
        {detail.targets.map(t => <div key={t.id} className="border rounded p-2 text-sm">账号 {t.account_id} · 商品 {t.item_id} · {labels[t.status] || t.status}<br/>计划 {t.scheduled_at} · 请求 {t.request_started_at || '未发起'}<br/>{t.message} {t.schedule_error}{t.retry_batch_id && <p>重试任务：{t.retry_batch_id}</p>}
          {t.status === 'unknown' && <button className="btn-ios-secondary" disabled={locked} onClick={() => setReconcile({ batchId, targetId: t.id, state: 'offline', note: '' })}>人工核对平台结果</button>}
          {t.status === 'reconciled' && <p>核对结论：{t.reconciled_state === 'offline' ? '平台已下架' : '平台仍在售'} · {t.reconciled_note} · {t.reconciled_at}</p>}
        </div>)}
        <button className="btn-ios-secondary" disabled={locked || !failed.length || !windowHours} onClick={() => openConfirm('retry')}>以新窗口重试未重试过的明确失败项（{failed.length}）</button>
        <details><summary>执行尝试</summary>{detail.attempts.map(a => <p key={a.id}>目标 {a.target_id}：{labels[a.status] || a.status} {a.message}</p>)}</details>
      </div>}
      {confirm && <div role="dialog" aria-modal="true" aria-label="下架确认" className="border rounded p-4 space-y-2">
        <p>商品：{confirm.title}；执行方式：{confirm.hours} 小时随机分散下架</p>
        <p>数量：{confirm.targets.length}</p>
        {confirm.targets.map(t => <p key={t.id}>账号 {t.account_id} · 商品 {t.item_id}</p>)}
        <button className="btn-ios-primary" disabled={busy} onClick={() => void submit()}>{busy ? '提交中' : '确认创建任务'}</button>
        <button className="btn-ios-secondary" disabled={busy} onClick={() => setConfirm(null)}>取消</button>
      </div>}
      {reconcile && <div role="dialog" aria-modal="true" aria-label="人工核对" className="border rounded p-4 space-y-2">
        <p>请先在平台人工确认该商品的真实状态，再选择结论。核对不会重发请求，也不会把未知记为失败。</p>
        <p>账号 {detail?.targets.find(t => t.id === reconcile.targetId)?.account_id} · 商品 {detail?.targets.find(t => t.id === reconcile.targetId)?.item_id}</p>
        <label className="flex gap-2"><input type="radio" name="platform-state" checked={reconcile.state === 'offline'} onChange={() => setReconcile({ ...reconcile, state: 'offline' })}/>平台已下架（本地同步为下架）</label>
        <label className="flex gap-2"><input type="radio" name="platform-state" checked={reconcile.state === 'active'} onChange={() => setReconcile({ ...reconcile, state: 'active' })}/>平台仍在售（本地保持原状）</label>
        <input className="input-ios" placeholder="核对依据（必填，例如：已在下架列表确认）" value={reconcile.note} onChange={e => setReconcile({ ...reconcile, note: e.target.value })}/>
        {reconcile.state === 'offline' && <p>若该商品本地状态已被改动，系统会保留平台已下架的事实并提示同步核对，不会覆盖你的人工修改。</p>}
        <button className="btn-ios-primary" disabled={busy || !reconcile.note.trim() || detail?.id !== reconcile.batchId || !detail.targets.some(t => t.id === reconcile.targetId && t.status === 'unknown')} onClick={() => void verify()}>{busy ? '提交中' : '保存核对结论'}</button>
        <button className="btn-ios-secondary" disabled={busy} onClick={() => setReconcile(null)}>取消</button>
      </div>}
    </div>
  </details>
}
