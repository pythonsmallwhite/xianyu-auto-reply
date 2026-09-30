import {useEffect, useRef, useState} from 'react';
import {Alert, ScrollView, Text, TextInput, View, useColorScheme} from 'react-native';
import {Button} from '@/components/ui';
import {colors} from '@/lib/theme';
import {listLinkedProducts, listOfflineBatches, getOfflineBatch, submitOfflineBatch, retryOfflineBatch, reconcileOfflineTarget, type LinkedProduct, type OfflineDetail, type OfflineTarget} from '@/api/wrappers/listing-actions';
const statusLabels:Record<string,string> = {pending:'待执行',running:'执行中',success:'成功',failed:'明确失败',unknown:'结果未知',deferred:'等待间隔',reconciled:'已人工核对'};
// 请求幂等键，不用于认证；服务器主键仍负责检测冲突。
const requestId = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, ch => {
  const r = Math.floor(Math.random()*16); return (ch === 'x' ? r : (r&3)|8).toString(16);
});
export default function OfflineBatchesScreen() {
  const c = colors[useColorScheme()==='dark'?'dark':'light'];
  const [products,setProducts] = useState<LinkedProduct[]>([]);
  const [productId,setProductId] = useState<number|null>(null);
  const [ids,setIds] = useState<number[]>([]);
  const [hours,setHours] = useState<number|null>(null);
  const [history,setHistory] = useState<{batch_id:string}[]>([]);
  const [batchId,setBatchId] = useState('');
  const [detail,setDetail] = useState<OfflineDetail|null>(null);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const lock = useRef(false);
  const keyRef = useRef<{key:string;id:string}|null>(null);
  const [reconcile,setReconcile] = useState<{batchId:string;target:OfflineTarget;state:'offline'|'active';note:string}|null>(null);
  const [refreshVersion,setRefreshVersion] = useState(0);
  const [notice,setNotice] = useState('');
  const [detailError,setDetailError] = useState('');
  const [saving,setSaving] = useState(false);
  const savingRef = useRef(false);
  const detailRef = useRef(detail);
  detailRef.current = detail;
  const detailGeneration = useRef(0);
  const contextGeneration = useRef(0);
  const product = products.find(p=>p.id===productId);
  useEffect(()=>{let live=true;listLinkedProducts().then(v=>{if(live)setProducts(v)}).catch(e=>{if(live)setError(e.message)});return()=>{live=false}},[]);
  useEffect(()=>{
    let live=true;contextGeneration.current++;detailGeneration.current++;
    setIds([]);setHours(null);setBatchId('');setDetail(null);setHistory([]);setReconcile(null);setNotice('');setError('');setDetailError('');
    if(productId) listOfflineBatches(productId).then(v=>{if(live)setHistory(v)}).catch(e=>{if(live)setError(e.message)});
    return()=>{live=false};
  },[productId]);
  useEffect(()=>{
    contextGeneration.current++;setDetail(null);setReconcile(null);setNotice('');setError('');setDetailError('');
    return()=>{contextGeneration.current++};
  },[productId,batchId]);
  useEffect(()=>{
    let live=true;let timer:ReturnType<typeof setTimeout>;setDetailError('');
    async function refresh(){
      if(savingRef.current)return;
      const generation=++detailGeneration.current;
      try{const value=await getOfflineBatch(batchId);if(live&&!savingRef.current&&generation===detailGeneration.current){
        setDetail(value);setDetailError('');
        setReconcile(prev=>prev&&!value.targets.some(t=>t.id===prev.target.id&&t.status==='unknown')?null:prev);
        if(!value.finished)timer=setTimeout(refresh,3000);
      }}
      catch(e){if(live&&!savingRef.current&&generation===detailGeneration.current)setDetailError(`详情刷新失败：${e instanceof Error?e.message:'查询失败'}`)}
    }
    if(batchId&&!saving)void refresh();return()=>{live=false;detailGeneration.current++;clearTimeout(timer)};
  },[productId,batchId,refreshVersion,saving]);
  const failed = detail?.targets.filter(t=>t.status==='failed'&&!t.retry_batch_id)||[];
  const unknown = detail?.targets.filter(t=>t.status==='unknown')||[];
  // 核对只上报真实平台状态并保存结论，不重发请求，因此不需要幂等请求 ID。
  const verify = () => void(async()=>{
    if(!reconcile||lock.current||!reconcile.note.trim()||reconcile.batchId!==batchId||detail?.id!==batchId||!detail.targets.some(t=>t.id===reconcile.target.id&&t.status==='unknown')) return;
    const {target,state,note} = reconcile;
    const generation=contextGeneration.current;
    detailGeneration.current++;
    savingRef.current=true;setSaving(true);
    lock.current=true;setBusy(true);
    try{
      setError('');setNotice('');
      const result=await reconcileOfflineTarget(batchId,target.id,state,note.trim());
      if(generation!==contextGeneration.current)return;
      setReconcile(null);setDetail(null);
      setNotice(`核对结论已保存，无需重新提交。${result.conflict?result.message||'平台已下架，但本地状态已变更，请同步核对':''}`);
    }catch(e){if(generation===contextGeneration.current){
      const lost=e instanceof TypeError||e instanceof Error&&'status' in e&&e.status===0;
      setError(`${lost?'保存结果未确认':'核对请求报错'}，请先取消核对并刷新详情确认保存结果，不要直接重发结论：${e instanceof Error?e.message:'请求失败'}`);
    }}
    finally{savingRef.current=false;setSaving(false);lock.current=false;setBusy(false);if(generation===contextGeneration.current)setRefreshVersion(v=>v+1)}
  })();
  const confirm = (retry:boolean) => {
    if(!product||!hours||lock.current) return;
    const generation=contextGeneration.current;
    const targets = retry?failed:product.listings.filter(l=>ids.includes(l.id));
    if(!targets.length)return;
    lock.current=true;setBusy(true);
    const done=()=>{lock.current=false;setBusy(false)};
    const key=JSON.stringify([retry,product.id,batchId,targets.map(t=>t.id),hours]);
    if(keyRef.current?.key!==key) keyRef.current={key,id:requestId()};
    Alert.alert('确认延迟下架', `商品：${product.title}\n数量：${targets.length}\n执行：${hours} 小时随机分散\n${targets.map(t=>`账号 ${t.account_id} · 商品 ${t.item_id}`).join('\n')}`, [
      {text:'取消',style:'cancel',onPress:done},
      {text:'确认创建',onPress:()=>{void(async()=>{try{
        const current=detailRef.current;
        if(generation!==contextGeneration.current||retry&&(current?.id!==batchId||targets.some(t=>!current.targets.some(v=>v.id===t.id&&v.status==='failed'&&!v.retry_batch_id)))) {
          setError('确认范围已失效，请重新确认');return;
        }
        setError('');
        const result=retry?await retryOfflineBatch(batchId,targets.map(t=>t.id),hours,keyRef.current!.id):await submitOfflineBatch(product.id,targets.map(t=>t.id),hours,keyRef.current!.id);
        if(generation!==contextGeneration.current)return;
        setHistory(prev=>[{batch_id:result.batch_id},...prev.filter(b=>b.batch_id!==result.batch_id)]);setBatchId(result.batch_id);setHours(null);setIds([]);keyRef.current=null;
      }catch(e){if(generation===contextGeneration.current)setError(e instanceof Error?e.message:'创建失败')}finally{done()}})()}},
    ],{cancelable:false});
  };
  return <ScrollView style={{backgroundColor:c.background}} contentContainerStyle={{padding:16,gap:12}}>
    <Text style={{color:c.text}}>仅操作明确关联商品。历史商品请用原有单件入口；恢复接口暂未接入。</Text>
    {!!notice&&<Text accessibilityRole="alert" style={{color:c.text}}>{notice}</Text>}
    {!!error&&<Text accessibilityRole="alert" style={{color:c.error}}>{error}</Text>}
    {!!detailError&&<Text accessibilityRole="alert" style={{color:c.error}}>{detailError}</Text>}
    {products.map(p=><Button key={p.id} label={`${productId===p.id?'✓ ':''}${p.title}`} disabled={busy} variant="secondary" onPress={()=>setProductId(p.id)}/>)}
    {product&&<View style={{gap:8}}><Button label="选择全部在售关联项" disabled={busy} onPress={()=>setIds(product.listings.filter(l=>l.state==='active').map(l=>l.id))}/>
      {product.listings.map(l=><Button key={l.id} variant="secondary" disabled={busy||l.state!=='active'} label={`${ids.includes(l.id)?'✓ ':''}账号 ${l.account_id} · 商品 ${l.item_id} · ${l.state}`} onPress={()=>setIds(prev=>prev.includes(l.id)?prev.filter(i=>i!==l.id):[...prev,l.id])}/>)}
    </View>}
    <Text style={{color:c.text}}>请选择本次窗口，重试也需重新选择</Text>
    <View style={{flexDirection:'row',flexWrap:'wrap',gap:8}}>{[1,3,5,12,24].map(h=><Button key={h} variant={hours===h?'primary':'secondary'} disabled={busy} label={`${h} 小时`} onPress={()=>setHours(h)}/>)}</View>
    <Button label="确认下架范围" disabled={busy||!hours||!ids.length} onPress={()=>confirm(false)}/>
    <Text style={{color:c.text}}>最近任务</Text>
    {history.map(b=><Button key={b.batch_id} label={b.batch_id} disabled={busy} variant="secondary" onPress={()=>{setBatchId(b.batch_id);setHours(null);setReconcile(null)}}/>)}
    {!!batchId&&<Button label="刷新任务详情" disabled={busy||!!reconcile} variant="secondary" onPress={()=>setRefreshVersion(v=>v+1)}/>}
    {detail&&<View style={{gap:8}}>
      {!!unknown.length&&<Text accessibilityRole="alert" style={{color:c.text}}>有 {unknown.length} 个结果未知项需要人工核对；核对完成前不能为同一商品另建任务，也不会自动重发。</Text>}
      <Text style={{color:c.text}}>窗口 {detail.window_hours} 小时 · 截止 {detail.deadline_at}（北京时间）</Text>
      {detail.targets.map(t=><View key={t.id} style={{gap:4}}>
        <Text style={{color:c.text}}>账号 {t.account_id} · 商品 {t.item_id} · {statusLabels[t.status]||t.status}{'\n'}计划 {t.scheduled_at} · 请求 {t.request_started_at||'未发起'}{'\n'}{t.message} {t.schedule_error}{t.retry_batch_id?` · 重试 ${t.retry_batch_id}`:''}</Text>
        {t.status==='unknown'&&<Button variant="secondary" disabled={busy||!!reconcile} label="人工核对平台结果" onPress={()=>setReconcile({batchId,target:t,state:'offline',note:''})}/>}
        {t.status==='reconciled'&&<Text style={{color:c.text}}>核对结论：{t.reconciled_state==='offline'?'平台已下架':'平台仍在售'} · {t.reconciled_note} · {t.reconciled_at}</Text>}
      </View>)}
      {reconcile&&<View style={{gap:8,borderWidth:1,borderColor:c.border,borderRadius:8,padding:8}}>
        <Text style={{color:c.text}}>请先在平台人工确认该商品真实状态。核对不会重发请求，也不会把未知记为失败。</Text>
        <Text style={{color:c.text}}>账号 {reconcile.target.account_id} · 商品 {reconcile.target.item_id}</Text>
        <Button variant={reconcile.state==='offline'?'primary':'secondary'} disabled={busy} label="平台已下架（本地同步为下架）" onPress={()=>setReconcile({...reconcile,state:'offline'})}/>
        <Button variant={reconcile.state==='active'?'primary':'secondary'} disabled={busy} label="平台仍在售（本地保持原状）" onPress={()=>setReconcile({...reconcile,state:'active'})}/>
        <TextInput style={{color:c.text,borderWidth:1,borderColor:c.border,borderRadius:8,padding:8}} editable={!busy} placeholder="核对依据（必填）" placeholderTextColor={c.textSecondary} value={reconcile.note} onChangeText={v=>setReconcile({...reconcile,note:v})}/>
        <Button label="保存核对结论" disabled={busy||!reconcile.note.trim()||detail?.id!==reconcile.batchId||!detail.targets.some(t=>t.id===reconcile.target.id&&t.status==='unknown')} onPress={verify}/>
        <Button variant="secondary" disabled={busy} label="取消核对" onPress={()=>setReconcile(null)}/>
      </View>}
      <Button label={`新窗口重试明确失败项 (${failed.length})`} disabled={busy||!!reconcile||!hours||!failed.length} onPress={()=>confirm(true)}/>
      {detail.attempts.map(a=><Text key={a.id} style={{color:c.text}}>尝试 {a.id} · 目标 {a.target_id} · {statusLabels[a.status]||a.status} {a.message}</Text>)}
    </View>}
  </ScrollView>;
}
