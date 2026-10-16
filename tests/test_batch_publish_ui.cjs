// Execute the real page, hooks, table and API wrappers with offline responses.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');
const root = path.resolve(__dirname, '../frontend/src');
const plain = value => JSON.parse(JSON.stringify(value));
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; }
const ok = data => ({ success: true, data });
const accounts = [{ id: 'a1', note: '账号一', remaining_publish_capacity: 5, reserved_publish_count: 1 }, { id: 'a2', note: '账号二', remaining_publish_capacity: 5 }];
const materials = [{ id: 1, title: '素材一', address: '离线素材所在地', images: [], price: 10 }, { id: 2, title: '缺地址素材', address: '  ', images: [], price: 20 }];
function batch(id = 'b1', extra = {}) {
  return { batch_id: id, window_hours: 1, address_mode: 'material', total: 4, success: 1, failed: 1, unknown: 1, skipped: 1, publishing: 0, pending: 0, timed_out: 0, finished: true, snapshot_available: true, created_at: '2026-10-16T10:00:00', account_statuses: [], ...extra };
}
function target(id, status = 'failed', extra = {}) {
  return { id, account_id: 'a1', title: `商品${id}`, material_id: 1, status, window_hours: 1, scheduled_at: '2026-10-16T10:05:00', available_at: '2026-10-16T10:06:00', finished_at: '2026-10-16T10:08:00', minimum_gap_seconds: 1, attempt_count: 0, attempts: [], ...extra };
}
const initialTargets = [target(11), target(12, 'success'), target(13, 'unknown'), target(14, 'skipped')];

function harness(options = {}) {
  const slots = [], effects = [], pendingEffects = [], timers = new Map(), calls = [], toasts = [], storage = new Map();
  let cursor = 0, dirty = false, tree, timerId = 0, bindings, mounted = true;
  if (options.saved) storage.set('batch_publish_active_batch_id:7', options.saved);
  const handlers = {
    history: page => ok({ list: page === 1 ? [batch('b1'), batch('b2')] : [batch('b3')], total: 12, page, page_size: 5 }),
    status: id => ok(batch(id)),
    targets: (id, page) => ok({ list: id === 'b1' ? initialTargets : [target(21, 'success', { title: `${id}-商品` })], total: 44, page, page_size: 20 }),
    publish: () => ok({ batch_id: 'created', total: 1 }),
    retry: () => ok({ retried: 1 }),
    reservations: () => ok([{ id: 'r1', publish_log_id: 1, status: 'unknown' }]),
    resolve: () => ok({}),
    capacity: () => ok({ remaining_publish_capacity: 7, reserved_publish_count: 1 }),
    ...options.handlers,
  };
  const invoke = (kind, ...args) => { calls.push({ kind, args: plain(args) }); return Promise.resolve().then(() => handlers[kind](...args)); };
  const changed = (deps, old) => !old || deps.length !== old.length || deps.some((value, i) => !Object.is(value, old[i]));
  const React = {
    Fragment: 'Fragment',
    createElement: (type, props, ...children) => ({ type, props: { ...props, children } }),
    useState: initial => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], value => { const next = typeof value === 'function' ? value(slots[i]) : value; if (!Object.is(next, slots[i])) { slots[i] = next; dirty = true; } }]; },
    useRef: initial => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useCallback: (fn, deps) => { const i = cursor++; if (changed(deps, slots[i]?.deps)) slots[i] = { deps, fn }; return slots[i].fn; },
    useEffect: (fn, deps) => { const i = cursor++; if (changed(deps, effects[i]?.deps)) pendingEffects.push(() => { effects[i]?.cleanup?.(); effects[i] = { deps, cleanup: fn() }; }); },
  };
  const api = {
    getMaterials: () => Promise.resolve(ok({ list: materials })),
    getPublishBatches: (page, size) => invoke('history', page, size),
    getBatchStatus: id => invoke('status', id),
    getPublishBatchTargets: (id, page, size) => invoke('targets', id, page, size),
    publishBatch: params => invoke('publish', params),
    retryPublishBatch: (id, ids, hours) => invoke('retry', id, ids, hours),
  };
  const accountApi = { getAccountDetails: () => Promise.resolve(accounts), getAccountPublishReservations: id => invoke('reservations', id), resolveAccountPublishReservation: (...args) => invoke('resolve', ...args), updateAccountPublishCapacity: (...args) => invoke('capacity', ...args) };
  const toast = value => toasts.push(value);
  let confirmation = true;
  const cache = new Map();
  function load(relative) {
    const filename = path.join(root, relative);
    if (cache.has(filename)) return cache.get(filename);
    let source = fs.readFileSync(filename, 'utf8');
    if (relative.replaceAll('\\', '/') === 'pages/product-publish/BatchPublish.tsx') source += '\nexport { BatchPublishContent };';
    if (options.mutate) source = options.mutate(relative, source);
    const expose = context => sourceFile => ts.visitNode(sourceFile, function visit(node) {
      if (ts.isFunctionDeclaration(node) && node.name?.text === 'BatchPublishContent') {
        const names = [];
        const collect = n => { if (ts.isIdentifier(n)) names.push(n.text); else if (ts.isArrayBindingPattern(n) || ts.isObjectBindingPattern(n)) n.elements.forEach(e => { if (ts.isBindingElement(e)) collect(e.name); }); };
        node.body.statements.forEach(s => { if (ts.isVariableStatement(s)) s.declarationList.declarations.forEach(d => collect(d.name)); });
        const assignment = ts.factory.createExpressionStatement(ts.factory.createCallExpression(ts.factory.createIdentifier('__capture'), undefined, [ts.factory.createObjectLiteralExpression(names.map(name => ts.factory.createShorthandPropertyAssignment(name)))]));
        return ts.factory.updateFunctionDeclaration(node, node.modifiers, node.asteriskToken, node.name, node.typeParameters, node.parameters, node.type, ts.factory.updateBlock(node.body, node.body.statements.flatMap(s => ts.isReturnStatement(s) ? [assignment, s] : [s])));
      }
      return ts.visitEachChild(node, visit, context);
    });
    const ctx = { exports: {}, React, console, Error, TypeError, __capture: value => { bindings = value; },
      setInterval: fn => { const id = ++timerId; timers.set(id, fn); return id; }, clearInterval: id => timers.delete(id),
      sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
      window: { confirm: () => confirmation },
      require: name => {
        if (name === 'react') return React;
        if (name === 'framer-motion') return { motion: { div: 'div' } };
        if (name === 'lucide-react') return new Proxy({}, { get: (_, name) => `icon-${name}` });
        if (name === '@/store/uiStore') return { useUIStore: () => ({ addToast: toast }) };
        if (name === '@/store/authStore') return { useAuthStore: select => select({ user: { user_id: 7 } }) };
        if (name === '@/api/productPublish') return api;
        if (name === '@/api/accounts') return accountApi;
        if (name.startsWith('./')) return load(path.join(path.dirname(relative), `${name.slice(2)}${name.includes('Presentation') ? '.ts' : '.tsx'}`));
        throw new Error(`Offline test blocked import: ${name}`);
      },
    };
    vm.createContext(ctx);
    vm.runInContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React }, transformers: { before: [expose] } }).outputText, ctx, { filename });
    cache.set(filename, ctx.exports);
    return ctx.exports;
  }
  const page = load('pages/product-publish/BatchPublish.tsx');
  function render() { if (!mounted) return; let limit = 0; do { assert.ok(++limit < 30, 'render loop'); dirty = false; cursor = 0; tree = page.BatchPublishContent({ userId: 7 }); while (pendingEffects.length) pendingEffects.shift()(); } while (dirty); }
  async function flush() { for (let i = 0; i < 8; i++) { await new Promise(resolve => setImmediate(resolve)); if (dirty) render(); } }
  function nodes() { const result = []; function walk(n) { if (n == null || typeof n !== 'object') return; if (Array.isArray(n)) return n.forEach(walk); if (typeof n.type === 'function') return walk(n.type(n.props)); result.push(n); walk(n.props?.children); } walk(tree); return result; }
  function textOf(n) { if (n == null || typeof n === 'boolean') return ''; if (typeof n !== 'object') return String(n); if (Array.isArray(n)) return n.map(textOf).join(''); if (typeof n.type === 'function') return textOf(n.type(n.props)); return textOf(n.props?.children); }
  const button = name => nodes().find(n => n.type === 'button' && (n.props['aria-label'] === name || textOf(n).includes(name)));
  async function click(name) { const n = button(name); assert.ok(n, `missing button ${name}`); assert.ok(!n.props.disabled, `disabled button ${name}`); n.props.onClick(); render(); await flush(); }
  async function input(name, value) { const n = nodes().find(n => n.props?.['aria-label'] === name); assert.ok(n, `missing input ${name}`); assert.ok(!n.props.disabled); n.props.onChange({ target: { value } }); render(); await flush(); }
  async function set(name, value) { bindings[name](value); render(); await flush(); }
  render();
  return { calls, handlers, toasts, timers, storage, flush, click, button, input, set, nodes, load, text: () => textOf(tree), get b() { return bindings; },
    confirm: value => { confirmation = value; },
    tick: async () => { [...timers.values()].forEach(fn => fn()); await flush(); },
    unmount: () => { effects.forEach(effect => effect?.cleanup?.()); mounted = false; },
  };
}

const scenarios = [
  ['历史无数据刷新会清除旧任务详情', async h => { await h.click('历史发布'); h.handlers.history = () => ok({ list: [], total: 0, page: 1 }); await h.click('刷新历史批量任务'); assert.equal(h.b.activeBatchId, null); assert.equal(h.b.progress, null); assert.equal(h.b.targets.length, 0); assert.equal(h.timers.size, 0); }],
  ['切批次隔离旧状态错误与旧详情成功', async h => { await h.click('历史发布'); const s = deferred(), t = deferred(); h.handlers.status = id => id === 'b1' ? s.promise : ok(batch(id)); h.handlers.targets = id => id === 'b1' ? t.promise : ok({ list: [target(21)], total: 1, page: 1 }); await h.click('刷新状态'); void h.b.loadTargets('b1'); await h.flush(); await h.click('查看批次 b2，结果未知'); s.reject(new Error('旧状态错误')); t.resolve(ok({ list: [target(99)], total: 1, page: 1 })); await h.flush(); assert.equal(h.b.statusError, ''); assert.equal(h.b.targets[0].id, 21); assert.equal(h.b.targetLoading, false); }],
  ['快切详情隔离旧错误，清除上一页失败选择', async h => { await h.click('历史发布'); await h.input('选择重试 a1 · 商品11'); const d = deferred(); h.handlers.targets = (id, page) => page === 2 ? d.promise : ok({ list: [target(33)], total: 44, page }); await h.click('任务详情下一页'); await h.click('任务详情下一页'); d.reject(new Error('旧分页错误')); await h.flush(); assert.equal(h.b.targetError, ''); assert.equal(h.b.targetPage, 3); assert.equal(h.b.selectedFailedTargets.size, 0); }],
  ['状态查询失败可刷新恢复且不自动开放提交', async h => { h.handlers.status = () => Promise.reject(new Error('离线状态失败')); await h.click('历史发布'); assert.ok(h.b.statusError); assert.equal(h.timers.size, 0); assert.equal(h.button('开始批量发布').props.disabled, true); h.handlers.status = id => ok(batch(id)); await h.click('刷新状态'); assert.equal(h.b.statusError, ''); assert.equal(h.b.progress.batch_id, 'b1'); }],
  ['不完整快照禁止失败重试与新提交', async h => { h.handlers.status = id => ok(batch(id, { snapshot_available: false })); await h.click('历史发布'); assert.ok(!h.button('重试选中')); await h.set('setSelectedFailedTargets', new Set([11])); await h.set('setRetryWindowHours', 1); await h.b.retrySelected(); assert.equal(h.calls.filter(c => c.kind === 'retry').length, 0); }],
  ['全选账号和取消唯一账号均清除立即发布', async h => { await h.flush(); await h.input('选择账号 a1'); await h.click('立即发布'); h.b.toggleAllAccounts(); await h.flush(); assert.equal(h.b.windowHours, null); await h.input('选择账号 a2'); await h.click('立即发布'); await h.input('选择账号 a1'); assert.equal(h.b.windowHours, null); assert.equal(h.button('立即发布').props.disabled, true); }],
  ['卸载后迟到状态不恢复轮询', async h => { const d = deferred(); h.handlers.status = () => d.promise; await h.click('历史发布'); h.unmount(); d.resolve(ok(batch('b1', { finished: false }))); await h.flush(); assert.equal(h.timers.size, 0); assert.equal(h.calls.filter(c => c.kind === 'targets').length, 0); }],
  ['历史默认收起且零历史请求，显式点击最近5次并选最新', async h => { await h.flush(); assert.equal(h.calls.length, 0); assert.equal(h.b.historyOpen, false); await h.click('历史发布'); assert.deepEqual(h.calls.find(c => c.kind === 'history').args, [1, 5]); assert.equal(h.b.activeBatchId, 'b1'); assert.ok(h.nodes().some(n => n.type === 'table')); }],
  ['历史空态与失败不混淆，失败可刷新恢复', async h => { h.handlers.history = () => Promise.reject(new Error('历史离线失败')); await h.click('历史发布'); assert.match(h.text(), /历史离线失败/); assert.ok(!h.text().includes('暂无历史发布记录')); h.handlers.history = () => ok({ list: [], total: 0, page: 1 }); await h.click('刷新历史批量任务'); assert.match(h.text(), /暂无历史发布记录/); }],
  ['历史关闭后迟到列表不展开或选批次', async h => { const d = deferred(); h.handlers.history = () => d.promise; await h.click('历史发布'); await h.click('历史发布'); d.resolve(ok({ list: [batch('old')], total: 1, page: 1 })); await h.flush(); assert.equal(h.b.historyOpen, false); assert.equal(h.b.activeBatchId, null); assert.equal(h.b.historyLoading, false); }],
  ['历史分页乱序响应只保留最后一页', async h => { await h.click('历史发布'); const d = deferred(); h.handlers.history = page => page === 2 ? d.promise : ok({ list: [batch('page3')], total: 12, page }); await h.click('历史任务下一页'); await h.click('历史任务下一页'); d.resolve(ok({ list: [batch('old-page2')], total: 12, page: 2 })); await h.flush(); assert.equal(h.b.historyPage, 3); assert.equal(h.b.activeBatchId, 'page3'); assert.ok(!h.text().includes('old-page2')); }],
  ['历史刷新途中手选批次优先', async h => { await h.click('历史发布'); const d = deferred(); h.handlers.history = () => d.promise; await h.click('刷新历史批量任务'); await h.click('查看批次 b2，结果未知'); d.resolve(ok({ list: [batch('b1'), batch('b2')], total: 12, page: 1 })); await h.flush(); assert.equal(h.b.activeBatchId, 'b2'); }],
  ['切批次隔离旧状态成功及详情失败', async h => { await h.click('历史发布'); const s = deferred(), t = deferred(); h.handlers.status = id => id === 'b1' ? s.promise : ok(batch(id)); h.handlers.targets = id => id === 'b1' ? t.promise : ok({ list: [target(21)], total: 1, page: 1 }); await h.click('刷新状态'); void h.b.loadTargets('b1'); await h.flush(); await h.click('查看批次 b2，结果未知'); s.resolve(ok(batch('b1', { finished: false }))); t.reject(new Error('旧详情错误')); await h.flush(); assert.equal(h.b.progress.batch_id, 'b2'); assert.equal(h.b.statusLoading, false); assert.equal(h.b.targetError, ''); assert.equal(h.timers.size, 0); }],
  ['快切详情分页隔离旧成功和加载状态', async h => { await h.click('历史发布'); const d = deferred(); h.handlers.targets = (id, page) => page === 2 ? d.promise : ok({ list: [target(33)], total: 44, page }); await h.click('任务详情下一页'); await h.click('任务详情下一页'); d.resolve(ok({ list: [target(99)], total: 44, page: 2 })); await h.flush(); assert.equal(h.b.targetPage, 3); assert.equal(h.b.targets[0].id, 33); assert.equal(h.b.targetLoading, false); }],
  ['轮询不抢占在途显式详情分页', async h => { h.handlers.status = id => ok(batch(id, { finished: false, status: 'running' })); await h.click('历史发布'); const d = deferred(); h.handlers.targets = () => d.promise; await h.click('任务详情下一页'); const count = h.calls.filter(c => c.kind === 'targets').length; await h.tick(); assert.equal(h.calls.filter(c => c.kind === 'targets').length, count); d.resolve(ok({ list: [target(22)], total: 44, page: 2 })); await h.flush(); assert.equal(h.b.targetPage, 2); assert.equal(h.b.targets[0].id, 22); }],
  ['详情失败可刷新且无伪空态', async h => { h.handlers.targets = () => Promise.reject(new Error('详情离线失败')); await h.click('历史发布'); assert.match(h.text(), /详情离线失败/); assert.ok(!h.text().includes('此批次暂无任务明细')); h.handlers.targets = () => ok({ list: [], total: 0, page: 1 }); await h.click('刷新详情'); assert.match(h.text(), /此批次暂无任务明细/); }],
  ['窗口无预选，立即发布仅一个账号，多选清除', async h => { await h.flush(); assert.equal(h.b.windowHours, null); assert.equal(h.button('立即发布').props.disabled, true); await h.input('选择账号 a1'); await h.click('立即发布'); assert.equal(h.b.windowHours, 0); await h.input('选择账号 a2'); assert.equal(h.b.windowHours, null); assert.equal(h.button('立即发布').props.disabled, true); await h.input('选择账号 a2'); assert.equal(h.b.windowHours, null); }],
  ['创建立即发布和默认素材地址精确请求，历史仍关闭', async h => { await h.flush(); await h.input('选择账号 a1'); await h.input('选择素材 素材一'); await h.click('立即发布'); await h.click('开始批量发布'); assert.deepEqual(h.calls.find(c => c.kind === 'publish').args[0], { account_ids: ['a1'], material_ids: [1], window_hours: 0, address_mode: 'material' }); assert.equal(h.calls.filter(c => c.kind === 'history').length, 0); assert.equal(h.b.historyOpen, false); assert.match(h.text(), /当前发布进度/); }],
  ['缺素材地址提前阻断且随机地址显式发送', async h => { await h.flush(); await h.input('选择账号 a1'); await h.input('选择素材 缺地址素材'); await h.click('1 小时'); assert.match(h.text(), /以下素材缺少所在地/); assert.equal(h.button('开始批量发布').props.disabled, true); await h.b.handleSubmit(); assert.equal(h.calls.filter(c => c.kind === 'publish').length, 0); const radio = h.nodes().find(n => n.type === 'input' && n.props.value === 'random'); radio.props.onChange(); await h.flush(); await h.click('开始批量发布'); assert.equal(h.calls.find(c => c.kind === 'publish').args[0].address_mode, 'random'); }],
  ['成功实际时间不能用计划时间，非成功不标已发布', async h => { const present = h.load('pages/product-publish/batchPublishPresentation.ts'); const success = present.targetPresentation(target(1, 'success', { finished_at: null })); assert.equal(success.actual, '未记录'); const fallback = present.targetPresentation(target(2, 'success', { finished_at: null, attempts: [{ attempt_no: 1, status: 'success', finished_at: '2026-10-16T10:09:00' }] })); assert.equal(fallback.actual, present.formatPublishTime('2026-10-16T10:09:00')); for (const state of ['pending', 'publishing', 'failed', 'unknown', 'skipped']) { const view = present.targetPresentation(target(3, state)); assert.notEqual(view.label, '已发布'); assert.equal(view.actual, '—'); } assert.equal(present.targetPresentation(target(4, 'pending')).expected, present.formatPublishTime('2026-10-16T10:06:00')); assert.equal(present.publishWindowLabel(0), '立即发布'); }],
  ['尝试记录仅展开显示，表格账号商品和时间列齐全', async h => { h.handlers.targets = () => ok({ list: [target(11, 'failed', { attempts: [{ id: 1, attempt_no: 1, status: 'failed', error_message: '尝试细节', finished_at: '2026-10-16T10:08:00' }] })], total: 1, page: 1 }); await h.click('历史发布'); assert.ok(!h.text().includes('尝试细节')); await h.click('展开 a1 · 商品11 的尝试记录'); assert.match(h.text(), /尝试细节/); for (const label of ['账号', '商品', '状态', '发布进度', '待发布预计时间', '成功实际发布时间', '错误 / 排程原因']) assert.ok(h.nodes().some(n => n.type === 'th' && n.props.children.includes(label))); }],
  ['失败重试只发送当前明确失败项，窗口无默认', async h => { await h.click('历史发布'); assert.equal(h.b.retryWindowHours, null); assert.equal(h.nodes().filter(n => n.type === 'input' && n.props['aria-label']?.startsWith('选择重试')).length, 1); await h.input('选择重试 a1 · 商品11'); await h.input('选择重试窗口', '3'); await h.click('重试选中'); assert.deepEqual(h.calls.find(c => c.kind === 'retry').args, ['b1', [11], 3]); }],
  ['过期失败选择和未知项不能提交重试', async h => { await h.click('历史发布'); await h.input('选择重试 a1 · 商品11'); await h.input('选择重试窗口', '1'); await h.set('setTargets', [target(11, 'unknown')]); await h.b.retrySelected(); assert.equal(h.calls.filter(c => c.kind === 'retry').length, 0); }],
  ['详情刷新清除已成功目标选择，翻页清除旧失败项', async h => { await h.click('历史发布'); await h.input('选择重试 a1 · 商品11'); h.handlers.targets = (id, page) => ok({ list: [target(11, 'success')], total: 44, page }); await h.b.loadTargets('b1'); await h.flush(); assert.equal(h.b.selectedFailedTargets.size, 0); await h.set('setSelectedFailedTargets', new Set([11])); await h.click('任务详情下一页'); assert.equal(h.b.selectedFailedTargets.size, 0); }],
  ['取消重试确认不请求，旧五档窗口保留', async h => { await h.click('历史发布'); await h.input('选择重试 a1 · 商品11'); await h.input('选择重试窗口', '1'); h.confirm(false); await h.click('重试选中'); assert.equal(h.calls.filter(c => c.kind === 'retry').length, 0); const select = h.nodes().find(n => n.props['aria-label'] === '选择重试窗口'); assert.ok(!JSON.stringify(select).includes('立即发布')); }],
  ['额度保存和unknown核对精确传参保持', async h => { await h.flush(); await h.input('a1 剩余可发布数量', '7'); await h.b.saveCapacity('a1'); await h.flush(); assert.deepEqual(h.calls.find(c => c.kind === 'capacity').args, ['a1', 7]); await h.b.openReservations('a1'); await h.flush(); await h.b.reconcileReservation('a1', 'r1', 'success'); assert.equal(h.calls.filter(c => c.kind === 'resolve').length, 0); await h.input('确认成功的平台商品 ID', 'offline-item'); await h.click('确认已发布'); assert.deepEqual(h.calls.find(c => c.kind === 'resolve').args, ['a1', 'r1', 'success', 'offline-item']); assert.equal(h.calls.filter(c => c.kind === 'history').length, 0); }],
];

async function main() {
  for (const [name, run] of scenarios) { const h = harness(); await run(h); h.unmount(); console.log(`PASS ${name}`); }
  const h = harness({ saved: 'active', handlers: { status: id => ok(batch(id, { finished: id !== 'active' })) } }); await h.flush(); assert.equal(h.calls.filter(c => c.kind === 'history').length, 0); assert.equal(h.b.activeBatchId, 'active'); await h.click('历史发布'); assert.equal(h.storage.get('batch_publish_active_batch_id:7'), 'active'); await h.input('选择账号 a1'); await h.input('选择素材 素材一'); await h.click('立即发布'); assert.equal(h.button('开始批量发布').props.disabled, true); await h.click('返回当前发布进度'); assert.equal(h.b.activeBatchId, 'active'); await h.click('查看批次 b2，结果未知'); await h.click('历史发布'); assert.equal(h.b.historyOpen, false); assert.equal(h.b.activeBatchId, 'active'); assert.equal(h.b.displaySource, 'current'); h.unmount(); console.log('PASS 恢复当前批次不展开历史，查看旧批次保留进行中保护并可返回');
  // Exercise the real API wrappers separately, including the new request contract.
  const requests = [], ctx = { exports: {}, URLSearchParams, require: name => { assert.equal(name, '@/utils/request'); return { post: (url, body) => { requests.push({ url, body: plain(body) }); }, get: url => requests.push({ url }) }; } };
  vm.createContext(ctx); vm.runInContext(ts.transpileModule(fs.readFileSync(path.join(root, 'api/productPublish.ts'), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText, ctx);
  ctx.exports.publishBatch({ account_ids: ['a1'], material_ids: [1], window_hours: 0, address_mode: 'material' }); ctx.exports.getPublishBatches(1, 5); ctx.exports.retryPublishBatch('b1', [11], 3);
  assert.equal(requests[0].body.window_hours, 0); assert.equal(requests[0].body.address_mode, 'material'); assert.match(requests[1].url, /page=1&page_size=5$/); assert.deepEqual(requests[2].body, { target_ids: [11], window_hours: 3 });
  console.log(`PASS API contract; ${scenarios.length + 2} offline cases, no network available`);
  const mutants = [
    ['取消历史显式开关', '历史默认收起且零历史请求，显式点击最近5次并选最新', (file, source) => file.endsWith('BatchPublish.tsx') ? source.replace("      const savedBatchId = sessionStorage.getItem(storageKey)", "      historyOpenRef.current = true; void loadHistory(); const savedBatchId = sessionStorage.getItem(storageKey)") : source],
    ['计划时间冒充成功实际时间', '成功实际时间不能用计划时间，非成功不标已发布', (file, source) => file.endsWith('batchPublishPresentation.ts') ? source.replace('target.finished_at || successfulAttempt?.finished_at', 'target.finished_at || successfulAttempt?.finished_at || target.scheduled_at') : source],
    ['取消立即发布多账号清理', '窗口无预选，立即发布仅一个账号，多选清除', (file, source) => file.endsWith('BatchPublish.tsx') ? source.replace('if (selectedAccounts.size !== 1 && windowHours === 0) setWindowHours(null)', 'if (false) setWindowHours(null)') : source],
    ['取消批次代次隔离', '切批次隔离旧状态成功及详情失败', (file, source) => file.endsWith('BatchPublish.tsx') ? source.replaceAll('if (generation !== batchGenerationRef.current) return', 'if (false) return') : source],
  ];
  for (const [name, scenario, mutate] of mutants) {
    let changed = false;
    const mutant = harness({ mutate: (file, source) => { const next = mutate(file, source); changed ||= next !== source; return next; } });
    let caught = false;
    try { await scenarios.find(([title]) => title === scenario)[1](mutant); } catch (error) { if (error.code !== 'ERR_ASSERTION') throw error; caught = true; } finally { mutant.unmount(); }
    assert.ok(changed && caught, `mutation escaped: ${name}`);
    console.log(`PASS mutation caught: ${name}`);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
