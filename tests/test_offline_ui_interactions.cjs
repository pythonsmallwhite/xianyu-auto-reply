// 离线执行真实组件、hook、effect 和事件处理器；不复制业务函数，不开放网络。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../xianyu-mobile/node_modules/typescript');

const sources = {
  web: '../frontend/src/pages/items/OfflineBatches.tsx',
  mobile: '../xianyu-mobile/app/(tabs)/mine/offline-batches.tsx',
};
const products = [1, 2].map(id => ({id, title: `商品${id}`, listings: [{id: id * 10, account_id: `a${id}`, item_id: `i${id}`, state: 'active'}]}));
const targetBases = new Map([['b1', 11], ['b2', 21], ['b-alt', 31], ['created', 41]]);
function detail(id, statuses = ['unknown', 'failed', 'success', 'failed']) {
  if (!targetBases.has(id)) targetBases.set(id, 51 + targetBases.size * 10);
  return {id, window_hours: 1, deadline_at: '离线时间', finished: true,
    targets: statuses.map((status, i) => ({id: i + targetBases.get(id), account_id: `${id}-a${i}`, item_id: `${id}-i${i}`, status, scheduled_at: '离线时间', ...(i === 3 ? {retry_batch_id: 'already'} : {})})), attempts: []};
}
function deferred() { let resolve, reject; const promise = new Promise((r, j) => {resolve = r; reject = j;}); return {promise, resolve, reject}; }
const plain = value => JSON.parse(JSON.stringify(value));
function harness(platform, mutate = false) {
  let source = fs.readFileSync(path.join(__dirname, sources[platform]), 'utf8');
  if (mutate) {
    const original = source;
    source = platform === 'web' ? source.replace('/targets/${targetId}/reconcile', '/targets/${targetId + 999}/reconcile') : source.replace('reconcileOfflineTarget(batchId,target.id,', 'reconcileOfflineTarget(batchId,target.id + 999,');
    assert.notEqual(source, original, '未命中核对 target 内存变异点');
  }
  const tree = ts.createSourceFile('page.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  // AST 只暴露组件当前词法绑定，组件与 JSX/effect 本身全部来自真实源码。
  const expose = context => root => ts.visitNode(root, function visit(node) {
    if (ts.isFunctionDeclaration(node) && /OfflineBatches/.test(node.name?.text || '')) {
      const names = [];
      const collect = n => { if (ts.isIdentifier(n)) names.push(n.text); else if (ts.isArrayBindingPattern(n) || ts.isObjectBindingPattern(n)) n.elements.forEach(e => {if (ts.isBindingElement(e)) collect(e.name);}); };
      node.body.statements.forEach(s => {if (ts.isVariableStatement(s)) s.declarationList.declarations.forEach(d => collect(d.name));});
      const assignment = ts.factory.createExpressionStatement(ts.factory.createAssignment(
        ts.factory.createPropertyAccessExpression(ts.factory.createIdentifier('globalThis'), 'bindings'),
        ts.factory.createObjectLiteralExpression(names.map(name => ts.factory.createShorthandPropertyAssignment(name)))));
      return ts.factory.updateFunctionDeclaration(node, node.modifiers, node.asteriskToken, node.name, node.typeParameters, node.parameters, node.type,
        ts.factory.updateBlock(node.body, node.body.statements.flatMap(s => ts.isReturnStatement(s) ? [assignment, s] : [s])));
    }
    return ts.visitEachChild(node, visit, context);
  });
  const slots = [], effects = [], pendingEffects = [], timers = new Map(), calls = [], alerts = [];
  let cursor = 0, dirty = false, ui, timerId = 0;
  let getDetail = id => Promise.resolve(detail(id));
  let postResult = () => Promise.resolve({batch_id: 'created', conflict: false});
  const React = {
    createElement: (type, props, ...children) => ({type, props: {...props, children}}),
    useState: initial => {const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], v => {const next = typeof v === 'function' ? v(slots[i]) : v; if (!Object.is(next, slots[i])) {slots[i] = next; dirty = true;}}];},
    useRef: initial => {const i = cursor++; if (!(i in slots)) slots[i] = {current: initial}; return slots[i];},
    useEffect: (fn, deps) => {const i = cursor++; const old = effects[i]; if (!old || deps.some((d, j) => !Object.is(d, old.deps[j]))) {pendingEffects.push(() => {old?.cleanup?.(); effects[i] = {deps, cleanup: fn()};});}},
  };
  const read = (kind, id) => {calls.push({method: 'GET', kind, id}); if (kind === 'products') return Promise.resolve(products); if (kind === 'history') return Promise.resolve([{batch_id: id === 2 || id === '2' ? 'b2' : 'b1'}, {batch_id: 'b-alt'}]); return getDetail(id);};
  const write = (kind, id, body, target) => {calls.push({method: 'POST', kind, id, ...(target === undefined ? {} : {target}), body: plain(body)}); return postResult(kind, id, body);};
  let businessFailure = '';
  const rejected = message => new Error(message);
  const wrappers = {
    listLinkedProducts: () => read('products'), listOfflineBatches: id => read('history', id), getOfflineBatch: id => read('detail', id),
    submitOfflineBatch: (id, ids, hours, requestId) => write('create', id, {listing_ids: ids, window_hours: hours, request_id: requestId}),
    retryOfflineBatch: (id, ids, hours, requestId) => write('retry', id, {target_ids: ids, window_hours: hours, request_id: requestId}),
    // wrapper 边界模拟其 confirmed=true 契约；组件仍须传入精确的前四个参数。
    reconcileOfflineTarget: (id, target, state, note) => {if (businessFailure) {write('reconcile', id, {platform_state: state, note, confirmed: true}, target); return Promise.reject(rejected(businessFailure));} return write('reconcile', id, {platform_state: state, note, confirmed: true}, target);},
  };
  const request = {
    get: async url => {const suffix = url.replace('/api/v1/internal-products', ''); const result = suffix === '' ? await read('products') : /^\/\d+\/offline-batches$/.test(suffix) ? await read('history', suffix.split('/')[1]) : await read('detail', suffix.split('/')[2]); return {success: true, data: result};},
    post: async (url, body) => {const parts = url.replace('/api/v1/internal-products/', '').split('/'); const kind = parts.includes('reconcile') ? 'reconcile' : parts.includes('retry') ? 'retry' : 'create'; const id = kind === 'create' ? parts[0] : parts[1]; const data = await write(kind, id, body, kind === 'reconcile' ? Number(parts[3]) : undefined); return businessFailure ? {success: false, message: businessFailure} : {success: true, data};},
  };
  const ctx = {exports: {}, React, console, Error, TypeError, crypto: {randomUUID: (() => {let n = 0; return () => `offline-${++n}`;})()},
    setTimeout: fn => {const id = ++timerId; timers.set(id, fn); return id;}, clearTimeout: id => timers.delete(id),
    require: name => {
      if (name === 'react') return React;
      if (name === 'react-native') return {Alert: {alert: (title, message, buttons) => alerts.push({title, message, buttons})}, useColorScheme: () => 'light', ScrollView: 'ScrollView', Text: 'Text', TextInput: 'TextInput', View: 'View'};
      if (name === '@/components/ui') return {Button: 'Button'};
      if (name === '@/lib/theme') return {colors: {light: {}, dark: {}}};
      if (name === '@/utils/request') return request;
      if (name === '@/api/wrappers/listing-actions') return wrappers;
      throw new Error(`禁止导入：${name}`);
    },
  };
  vm.createContext(ctx);
  vm.runInContext(ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React}, transformers: {before: [expose]}}).outputText, ctx);
  const component = ctx.exports.OfflineBatches || ctx.exports.default;
  function render() {
    do {dirty = false; cursor = 0; ui = component(); while (pendingEffects.length) pendingEffects.shift()();} while (dirty);
  }
  async function flush() {for (let i = 0; i < 6; i++) {await new Promise(r => setImmediate(r)); if (dirty) render();}}
  function nodes() {const out = []; function visit(n) {if (!n || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(visit); out.push(n); visit(n.props?.children);} visit(ui); return out;}
  function text(n) {if (n == null || typeof n === 'boolean') return ''; if (typeof n !== 'object') return String(n); if (Array.isArray(n)) return n.map(text).join(''); return n.props?.label || text(n.props?.children);}
  function button(label) {return nodes().find(n => ['button', 'Button'].includes(n.type) && text(n).includes(label));}
  async function click(label) {const n = button(label); assert.ok(n, `缺少按钮：${label}`); assert.ok(!n.props.disabled, `按钮不可用：${label}`); (n.props.onClick || n.props.onPress)(); await flush();}
  async function set(name, value) {ctx.bindings[name](value); render(); await flush();}
  async function chooseProduct(id = 1) {await set('setProductId', platform === 'web' ? String(id) : id);}
  async function chooseBatch(id = 'b1') {if (platform === 'web') {nodes().find(n => n.type === 'select' && text(n).includes('查看最近')).props.onChange({target: {value: id}});} else {await click(id); return;} render(); await flush();}
  async function setup() {await chooseProduct(); await chooseBatch();}
  async function hours(value = 1) {await set(platform === 'web' ? 'setWindowHours' : 'setHours', platform === 'web' ? String(value) : value);}
  async function openCreate() {await click('确认下架范围');}
  async function confirmSubmit() {if (platform === 'web') await click('确认创建任务'); else {const b = alerts.at(-1).buttons.find(b => b.text === '确认创建'); b.onPress(); await flush();}}
  async function openVerify() {await click('人工核对平台结果'); await set('setReconcile', {...ctx.bindings.reconcile, note: '已离线核实'});}
  async function openRetry() {await click(platform === 'web' ? '以新窗口重试' : '新窗口重试');}
  function dialogText() {return platform === 'web' ? text(nodes().find(n => n.props?.['aria-label'] === '下架确认')) : alerts.at(-1).message;}
  function startVerify() {ctx.bindings.verify(); if (dirty) render();}
  render();
  return {ctx, calls, alerts, timers, flush, set, setup, chooseProduct, chooseBatch, hours, click, button, openCreate, confirmSubmit, openVerify, openRetry, dialogText, startVerify,
    posts: () => calls.filter(c => c.method === 'POST'), text: () => text(ui),
    getDetail: fn => {getDetail = fn;}, postResult: fn => {postResult = fn;}, businessFailure: message => {businessFailure = message;},
    runTimers: async () => {const waiting = Array.from(timers.values()); timers.clear(); waiting.forEach(fn => fn()); await flush();},
    tick: async () => {const entry = timers.entries().next().value; assert.ok(entry, '未恢复轮询'); timers.delete(entry[0]); entry[1](); await flush();},
  };
}

async function exactReconcile(h) {
  await h.chooseProduct(); await h.chooseBatch('b-alt'); await h.openVerify();
  await h.set('setReconcile', {...h.ctx.bindings.reconcile, state: 'active', note: '  独立任务已核实  '});
  h.startVerify(); await h.flush();
  assert.equal(h.posts().length, 1);
  assert.deepEqual(h.posts()[0], {method: 'POST', kind: 'reconcile', id: 'b-alt', target: 31, body: {platform_state: 'active', note: '独立任务已核实', confirmed: true}});
}
const scenarios = [
  ['取消确认零 POST', async h => {await h.setup(); await h.click('选择全部在售关联项'); await h.hours(); await h.openCreate(); if (h.ctx.exports.OfflineBatches) await h.click('取消'); else {h.alerts.at(-1).buttons[0].onPress(); await h.flush();} assert.equal(h.posts().length, 0);}],
  ['无窗口创建和重试均阻断', async h => {await h.setup(); await h.click('选择全部在售关联项'); assert.equal(h.button('确认下架范围').props.disabled, true); if (h.ctx.bindings.submit) {h.ctx.bindings.openConfirm('create'); h.ctx.bindings.openConfirm('retry'); await h.ctx.bindings.submit();} else {h.ctx.bindings.confirm(false); h.ctx.bindings.confirm(true);} assert.equal(h.posts().length, 0);}],
  ['创建网络重试复用请求 ID', async h => {await h.setup(); await h.click('选择全部在售关联项'); await h.hours(); h.postResult(() => Promise.reject(new Error('离线断网'))); await h.openCreate(); await h.confirmSubmit(); if (!h.ctx.bindings.submit) await h.openCreate(); await h.confirmSubmit(); assert.equal(h.posts().length, 2); assert.ok(h.posts()[0].body.request_id); assert.equal(h.posts()[0].body.request_id, h.posts()[1].body.request_id);}],
  ['失败重试仅含未重试的明确失败项并复用 ID', async h => {await h.setup(); await h.hours(3); h.postResult(() => Promise.reject(new Error('离线断网'))); const retry = h.ctx.bindings.submit ? '以新窗口重试' : '新窗口重试'; await h.click(retry); await h.confirmSubmit(); if (!h.ctx.bindings.submit) await h.click(retry); await h.confirmSubmit(); assert.equal(h.posts().length, 2); assert.deepEqual(h.posts()[0].body.target_ids, [12]); assert.equal(h.posts()[0].body.window_hours, 3); assert.equal(h.posts()[0].body.request_id, h.posts()[1].body.request_id);}],
  ['unknown/success 禁止失败重试', async h => {h.getDetail(id => Promise.resolve(detail(id, ['unknown', 'success']))); await h.setup(); await h.hours(); if (h.ctx.bindings.submit) {h.ctx.bindings.openConfirm('retry'); await h.ctx.bindings.submit();} else h.ctx.bindings.confirm(true); assert.equal(h.posts().length, 0);}],
  ['切商品清理核对上下文', async h => {await h.setup(); await h.openVerify(); await h.chooseProduct(2); assert.equal(h.ctx.bindings.reconcile, null); assert.equal(h.ctx.bindings.detail, null);}],
  ['切任务清理核对上下文', async h => {await h.setup(); await h.openVerify(); await h.chooseBatch('b-alt'); assert.equal(h.ctx.bindings.reconcile, null);}],
  ['核对拒绝跨任务 target', async h => {await h.setup(); await h.openVerify(); const stale = plain(h.ctx.bindings.reconcile); await h.chooseBatch('b-alt'); await h.set('setReconcile', stale); h.ctx.bindings.verify(); await h.flush(); assert.equal(h.posts().length, 0);}],
  ['核对仅接受当前 unknown', async h => {await h.setup(); await h.openVerify(); await h.set('setDetail', detail('b1', ['success'])); h.ctx.bindings.verify(); await h.flush(); assert.equal(h.posts().length, 0);}],
  ['详情失败显式刷新恢复轮询', async h => {await h.chooseProduct(); h.getDetail(() => Promise.reject(new Error('详情离线失败'))); await h.chooseBatch(); assert.match(h.text(), /详情离线失败/); assert.equal(h.timers.size, 0); h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.click('刷新任务详情'); assert.equal(h.ctx.bindings.detail.id, 'b1'); assert.ok(!h.ctx.bindings.error); await h.tick();}],
  ['快速切任务隔离旧 GET 成功', async h => {await h.chooseProduct(); const d = deferred(); h.getDetail(id => id === 'b1' ? d.promise : Promise.resolve(detail(id))); await h.chooseBatch(); await h.chooseBatch('b-alt'); d.resolve(detail('b1')); await h.flush(); assert.equal(h.ctx.bindings.detail.id, 'b-alt');}],
  ['快速切商品隔离旧 GET 错误', async h => {await h.chooseProduct(); const d = deferred(); h.getDetail(id => id === 'b1' ? d.promise : Promise.resolve(detail(id))); await h.chooseBatch(); await h.chooseProduct(2); await h.chooseBatch('b2'); d.reject(new Error('旧错误')); await h.flush(); assert.equal(h.ctx.bindings.detail.id, 'b2'); assert.ok(!h.text().includes('旧错误'));}],
  ['核对保存成功 GET 失败不得暗示重发', async h => {await h.setup(); await h.openVerify(); h.getDetail(() => Promise.reject(new Error('GET失败'))); h.ctx.bindings.verify(); await h.flush(); assert.equal(h.posts().length, 1); assert.equal(h.ctx.bindings.reconcile, null); assert.match(h.text(), /核对结论已保存/); assert.match(h.text(), /详情刷新失败/); assert.ok(!h.text().includes('重新提交结论'));}],
  ['保存后 GET 失败保留冲突警告', async h => {await h.setup(); await h.openVerify(); h.postResult(() => Promise.resolve({conflict: true, message: '离线本地状态冲突'})); h.getDetail(() => Promise.reject(new Error('GET失败'))); h.ctx.bindings.verify(); await h.flush(); assert.match(h.text(), /核对结论已保存/); assert.match(h.text(), /详情刷新失败/); assert.match(h.text(), /离线本地状态冲突/);}],
  ['核对旧 POST 成功隔离新任务表单', async h => {await h.setup(); await h.openVerify(); const d = deferred(); h.postResult(() => d.promise); h.ctx.bindings.verify(); await h.flush(); await h.set('setBatchId', 'b-alt'); await h.set('setReconcile', {batchId: 'b-alt', targetId: detail('b-alt').targets[0].id, target: detail('b-alt').targets[0], state: 'active', note: '新结论'}); d.resolve({conflict: true, message: '旧冲突'}); await h.flush(); assert.equal(h.ctx.bindings.detail.id, 'b-alt'); assert.equal(h.ctx.bindings.reconcile.note, '新结论'); assert.ok(!h.text().includes('旧冲突'));}],
  ['核对旧 GET 成功隔离新任务详情', async h => {await h.setup(); await h.openVerify(); const d = deferred(); h.getDetail(id => id === 'b1' ? d.promise : Promise.resolve(detail(id))); h.ctx.bindings.verify(); await h.flush(); await h.set('setBatchId', 'b-alt'); d.resolve(detail('b1')); await h.flush(); assert.equal(h.ctx.bindings.detail.id, 'b-alt');}],
  ['取消核对零 POST', async h => {await h.setup(); await h.openVerify(); await h.click(h.ctx.bindings.submit ? '取消' : '取消核对'); assert.equal(h.posts().length, 0); assert.equal(h.ctx.bindings.reconcile, null);}],
  ['空核对依据阻断 POST', async h => {await h.setup(); await h.openVerify(); await h.set('setReconcile', {...h.ctx.bindings.reconcile, note: '  '}); h.ctx.bindings.verify(); await h.flush(); assert.equal(h.posts().length, 0);}],
  ['核对 POST 失败保留表单和结论', async h => {await h.setup(); await h.openVerify(); h.postResult(() => Promise.reject(new Error('POST失败'))); h.ctx.bindings.verify(); await h.flush(); assert.equal(h.posts().length, 1); assert.equal(h.ctx.bindings.reconcile.note, '已离线核实'); assert.match(h.text(), /POST失败/); assert.ok(!h.text().includes('核对结论已保存'));}],
  ['保存后刷新仅 GET 并保留冲突警告', async h => {await h.setup(); await h.openVerify(); h.postResult(() => Promise.resolve({conflict: true, message: '离线本地状态冲突'})); h.getDetail(() => Promise.reject(new Error('GET失败'))); h.ctx.bindings.verify(); await h.flush(); h.getDetail(id => Promise.resolve(detail(id, ['reconciled']))); await h.click('刷新任务详情'); assert.equal(h.posts().length, 1); assert.equal(h.ctx.bindings.error, ''); assert.equal(h.ctx.bindings.detail.targets[0].status, 'reconciled'); assert.match(h.text(), /离线本地状态冲突/); assert.ok(!h.button('人工核对平台结果'));}],
  ['同任务刷新隔离旧 GET 成功', async h => {await h.setup(); const d = deferred(); h.getDetail(() => d.promise); await h.click('刷新任务详情'); h.getDetail(id => Promise.resolve({...detail(id), deadline_at: '新详情'})); await h.click('刷新任务详情'); d.resolve({...detail('b1'), deadline_at: '旧详情', finished: false}); await h.flush(); assert.equal(h.ctx.bindings.detail.deadline_at, '新详情'); assert.equal(h.timers.size, 0);}],
  ['同任务刷新隔离旧 GET 错误', async h => {await h.setup(); const d = deferred(); h.getDetail(() => d.promise); await h.click('刷新任务详情'); h.getDetail(id => Promise.resolve(detail(id))); await h.click('刷新任务详情'); d.reject(new Error('旧刷新错误')); await h.flush(); assert.equal(h.ctx.bindings.error, ''); assert.equal(h.ctx.bindings.detail.id, 'b1');}],
  ['切任务隔离旧核对 POST 错误', async h => {await h.setup(); await h.openVerify(); const d = deferred(); h.postResult(() => d.promise); h.ctx.bindings.verify(); await h.flush(); await h.set('setBatchId', 'b-alt'); d.reject(new Error('旧核对错误')); await h.flush(); assert.equal(h.ctx.bindings.detail.id, 'b-alt'); assert.equal(h.ctx.bindings.error, '');}],
  ['切商品隔离旧创建响应', async h => {await h.setup(); await h.click('选择全部在售关联项'); await h.hours(); const d = deferred(); h.postResult(() => d.promise); await h.openCreate(); await h.confirmSubmit(); await h.chooseProduct(2); await h.set('setBatchId', 'b2'); d.resolve({batch_id: 'old-created'}); await h.flush(); assert.equal(h.ctx.bindings.batchId, 'b2'); assert.equal(h.ctx.bindings.detail.id, 'b2'); assert.ok(!h.ctx.bindings.history.some(b => b.batch_id === 'old-created'));}],
  ['轮询在途旧详情不能覆盖已保存核对', async h => {await h.setup(); const d = deferred(); h.getDetail(() => d.promise); await h.click('刷新任务详情'); await h.openVerify(); h.getDetail(id => Promise.resolve(detail(id, ['reconciled']))); h.ctx.bindings.verify(); await h.flush(); d.resolve({...detail('b1'), finished: false}); await h.flush(); assert.equal(h.ctx.bindings.detail.targets[0].status, 'reconciled'); assert.equal(h.timers.size, 0);}],
  ['核对成功精确 batch target state note confirmed', exactReconcile],
  ['旧 target 即使改成当前 batch 上下文仍拒绝', async h => {await h.setup(); await h.openVerify(); const old = plain(h.ctx.bindings.reconcile); await h.chooseBatch('b-alt'); await h.set('setReconcile', {...old, batchId: 'b-alt'}); h.startVerify(); await h.flush(); assert.equal(h.posts().length, 0); assert.equal(h.button('保存核对结论').props.disabled, true);}],
  ['核对成功后未结束批次继续轮询', async h => {h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.setup(); await h.openVerify(); const post=deferred(); h.postResult(()=>post.promise); h.startVerify(); await h.flush(); h.getDetail(id=>Promise.resolve({...detail(id, ['reconciled','pending']), finished:false})); post.resolve({conflict:false}); await h.flush(); assert.match(h.text(), /核对结论已保存/); assert.equal(h.ctx.bindings.reconcile,null); await h.tick(); await h.tick(); assert.equal(h.posts().length,1); assert.equal(h.ctx.bindings.detail.targets[0].status,'reconciled');}],
  ['重试弹确认后轮询新增失败不扩大范围', async h => {
    h.getDetail(id => Promise.resolve({...detail(id, ['unknown','failed','pending']), finished: false})); await h.setup(); await h.hours(3); await h.openRetry();
    h.getDetail(id => Promise.resolve({...detail(id, ['unknown','failed','failed']), finished: false})); await h.runTimers();
    assert.ok(!h.dialogText().includes('b1-i2'), '确认展示被轮询扩大'); await h.confirmSubmit(); assert.deepEqual(h.posts()[0].body.target_ids, [12]);
  }],
  ['重试确认目标已失效拒绝而非换范围', async h => {
    h.getDetail(id => Promise.resolve({...detail(id, ['unknown','failed','pending']), finished: false})); await h.setup(); await h.hours(); await h.openRetry();
    await h.set('setDetail', {...detail('b1', ['unknown','success','failed']), finished: false}); await h.confirmSubmit(); assert.equal(h.posts().length, 0); assert.match(h.text(), /范围.*失效|重新确认/);
  }],
  ['核对 POST 失败不使在途 GET 的后续轮询消失', async h => {
    h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.setup(); await h.openVerify();
    const get = deferred(), post = deferred(); h.getDetail(() => get.promise); await h.tick(); h.postResult(() => post.promise); h.startVerify(); await h.flush();
    h.getDetail(id => Promise.resolve({...detail(id), finished: false})); get.resolve({...detail('b1'), finished: false}); post.reject(new TypeError('响应丢失')); await h.flush();
    assert.equal(h.ctx.bindings.busy, false); assert.match(h.text(), /保存结果未确认/); assert.ok(h.timers.size > 0, 'POST 失败后没有恢复轮询'); await h.tick(); assert.match(h.text(), /保存结果未确认/);
  }],
  ['已排 timer 在 POST 期间不启动 GET 且响应丢失后可恢复', async h => {
    h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.setup(); await h.openVerify(); const post = deferred(); h.postResult(() => post.promise);
    h.startVerify(); await h.flush(); const before = h.calls.filter(c => c.method === 'GET').length;
    h.getDetail(id => Promise.resolve({...detail(id, ['reconciled','pending']), finished: false})); await h.runTimers(); assert.equal(h.calls.filter(c => c.method === 'GET').length, before, '保存期间 timer 发起 GET');
    post.reject(new TypeError('响应丢失')); await h.flush(); assert.match(h.text(), /保存结果未确认/); assert.equal(h.ctx.bindings.detail.targets[0].status, 'reconciled'); assert.equal(h.ctx.bindings.reconcile, null);
    assert.equal(h.button('刷新任务详情').props.disabled, false); await h.click('刷新任务详情'); await h.tick(); assert.equal(h.posts().length, 1);
  }],
  ['明确业务 POST 错误恢复 GET 后不消失且可取消', async h => {
    h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.setup(); await h.openVerify(); h.businessFailure('业务明确拒绝'); h.startVerify(); await h.flush();
    assert.match(h.text(), /业务明确拒绝/); assert.ok(!h.text().includes('核对结论已保存')); assert.ok(!h.text().includes('保存结果未确认')); assert.ok(h.timers.size > 0);
    await h.tick(); assert.match(h.text(), /业务明确拒绝/); await h.click(h.ctx.bindings.submit ? '取消' : '取消核对'); await h.click('刷新任务详情'); assert.equal(h.posts().length, 1);
  }],
  ['保存响应丢失与详情 GET 失败分别提示且可取消刷新', async h => {
    h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.setup(); await h.openVerify(); h.postResult(() => Promise.reject(new TypeError('响应丢失'))); h.getDetail(() => Promise.reject(new Error('恢复GET失败')));
    h.startVerify(); await h.flush(); assert.match(h.text(), /保存结果未确认/); assert.match(h.text(), /详情刷新失败/);
    await h.click(h.ctx.bindings.submit ? '取消' : '取消核对'); h.getDetail(id => Promise.resolve({...detail(id), finished: false})); await h.click('刷新任务详情'); await h.tick(); assert.equal(h.posts().length, 1);
  }],
];
(async () => {
  let passed = 0, failed = 0;
  const only = process.env.OFFLINE_UI_ONLY;
  for (const platform of Object.keys(sources)) for (let i = 0; i < scenarios.length; i++) {
    const [name, test] = scenarios[i];
    if (only && !`${platform}:${i + 1}`.includes(only) && !name.includes(only)) continue;
    try {const h = harness(platform, !!process.env.OFFLINE_UI_MUTATE_TARGET); await h.flush(); await test(h); passed++; console.log(`PASS ${platform}:${i + 1} ${name}`);}
    catch (e) {failed++; console.error(`FAIL ${platform}:${i + 1} ${name}: ${e.message}`);}
  }
  console.log(`离线 UI 回归：${passed} 通过，${failed} 失败，共 ${passed + failed} 场景；真实网络调用 0。`);
  if (failed) process.exitCode = 1;
})().catch(e => {console.error(e); process.exitCode = 1;});
