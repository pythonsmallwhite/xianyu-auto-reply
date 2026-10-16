// Offline execution of real TypeScript functions; no platform requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('../xianyu-mobile/node_modules/typescript');
const read = (file) => fs.readFileSync(path.join(__dirname, '..', file), 'utf8');
const source = read('xianyu-mobile/app/(tabs)/mine/materials.tsx');
const publishSource = read('xianyu-mobile/app/(tabs)/mine/product-publish.tsx');
const tree = ts.createSourceFile('materials.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const declarations = {};
function walk(node) {
  if (ts.isFunctionDeclaration(node) && node.name) declarations[node.name.text] = node.getText(tree);
  if (ts.isVariableDeclaration(node) && node.initializer) declarations[node.name.getText(tree)] = 'const ' + node.getText(tree) + ';';
  ts.forEachChild(node, walk);
}
walk(tree);
const compile = (code) => ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const plain = (value) => JSON.parse(JSON.stringify(value));
let passed = 0;
async function test(name, fn) { await fn(); passed++; console.log('PASS ' + name); }
const details = { id: 7, user_id: 11, title: 'Original', description: 'Description', price: 12, images: ['/static/a.jpg'], quantity: 1, condition: '全新', shipping_method: 'free', postage: 5, address: 'Saved address', address_expected_text: 'Saved hierarchy', sku_rows: [{ price: 12 }], videos: [{ url: '/video.mp4' }], platform_attributes: [{ property_id: 'brand' }] };
function harness() {
  const state = { editor: null, materials: [], page: 1, total: 0, loading: true, refreshing: false, loadingMore: false, loadError: '', detailLoading: false, saving: false, uploading: false, recommending: false, deleting: false, candidates: [] };
  const alerts = [], calls = [];
  const context = {
    ...state, userId: 11, fromPublish: false, PAGE_SIZE: 50,
    mounted: { current: true }, editorVersion: { current: 0 }, categoryVersion: { current: 0 },
    listRequest: { current: 0 }, detailRequest: { current: 0 }, uploadPending: { current: false }, mutationPending: { current: false },
    Alert: { alert: (...args) => alerts.push(args) },
    useCallback: (fn) => fn, router: { back: () => calls.push(['back']) },
    getPublishMaterials: async () => ({ list: [], total: 0 }), getMaterial: async () => details,
    createMaterial: async (body) => { calls.push(['create', body]); return 8; },
    updateMaterial: async (id, body) => calls.push(['update', id, body]),
    deleteMaterial: async (id) => calls.push(['delete', id]),
    ImagePicker: { launchImageLibraryAsync: async () => ({ canceled: false, assets: [{ uri: 'file:///a.jpg' }] }) },
    uploadProductImages: async () => ({ paths: ['/a'], urls: ['/static/a.jpg'] }),
    recommendMaterialCategory: async () => [],
  };
  for (const key of Object.keys(state)) context['set' + key[0].toUpperCase() + key.slice(1)] = (next) => { context[key] = typeof next === 'function' ? next(context[key]) : next; };
  vm.createContext(context);
  const names = ['draftFromMaterial', 'previewUrl', 'categoryLabel', 'changedMaterialFields', 'loadPage', 'openEditor', 'openNew', 'closeEditor', 'updateDraft', 'pickImages', 'recommendCategory', 'chooseCategory', 'save', 'confirmDelete'];
  vm.runInContext(compile(names.map((name) => declarations[name]).join('\n') + '\nthis.api = {' + names.join(',') + '};'), context);
  context.editor = { id: 7, original: details, draft: context.api.draftFromMaterial(details), categoryChanged: false };
  return { context, api: context.api, alerts, calls };
}
function wrapperHarness() {
  const calls = []; let response;
  const client = Object.fromEntries(['GET', 'POST', 'PUT', 'DELETE'].map((method) => [method, async (url, options) => { calls.push({ method, url, options }); return { data: response }; }]));
  class FakeFormData { fields = []; append(...args) { this.fields.push(args); } }
  const context = { exports: {}, require: () => ({ getApiClient: async () => client }), FormData: FakeFormData };
  vm.runInNewContext(compile(read('xianyu-mobile/api/wrappers/product-publish.ts')), context);
  return { api: context.exports, calls, reply: (value) => { response = value; } };
}

(async () => {
  await test('CRUD matches backend methods and paths', async () => {
    const h = wrapperHarness(); h.reply({ success: true, data: { id: 7 } });
    assert.equal(await h.api.createMaterial({ title: 'New' }), 7);
    assert.equal((await h.api.getMaterial(7)).id, 7);
    h.reply({ success: true }); await h.api.updateMaterial(7, { price: 20 }); await h.api.deleteMaterial(7);
    assert.deepEqual(h.calls.map(({ method, url }) => [method, url]), [['POST', '/api/v1/product-publish/materials'], ['GET', '/api/v1/product-publish/materials/7'], ['PUT', '/api/v1/product-publish/materials/7'], ['DELETE', '/api/v1/product-publish/materials/7']]);
    assert.deepEqual(plain(h.calls[2].options.body), { price: 20 });
    const backend = read('backend-web/app/api/routes/product_publish.py');
    for (const [method, route] of [['post', '/materials'], ['get', '/materials/{material_id}'], ['put', '/materials/{material_id}'], ['delete', '/materials/{material_id}']]) assert.ok(backend.includes('@router.' + method + '("' + route + '"'));
  });
  await test('business failures without data and empty mutations reject', async () => {
    const h = wrapperHarness(); h.reply({ success: false, message: 'denied' });
    await assert.rejects(h.api.updateMaterial(7, {}), /denied/); await assert.rejects(h.api.deleteMaterial(7), /denied/); await assert.rejects(h.api.createMaterial({}), /denied/);
    h.reply(undefined); await assert.rejects(h.api.updateMaterial(7, {}), /无法确认/); await assert.rejects(h.api.deleteMaterial(7), /无法确认/);
  });
  await test('multipart serializer preserves files and rejects incomplete uploads', async () => {
    const h = wrapperHarness(); h.reply({ success: true, data: { urls: ['/static/a.jpg'], paths: ['/a.jpg'] } });
    await h.api.uploadProductImages(['file:///a.jpg']); const { options, url } = h.calls[0];
    assert.equal(url, '/api/v1/product-publish/upload/images'); assert.equal(options.bodySerializer(options.body), options.body);
    assert.equal(options.body.fields[0][0], 'files'); assert.equal(options.body.fields[0][1].type, 'image/jpeg');
    h.reply({ success: true, data: { urls: [], paths: [] } }); await assert.rejects(h.api.uploadProductImages(['file:///a.jpg']), /响应无效/);
  });
  await test('list and details enforce current user ownership', async () => {
    const h = harness(); h.context.getPublishMaterials = async () => ({ list: [details, { ...details, id: 9, user_id: 12 }], total: 60 });
    await h.api.loadPage(1); assert.deepEqual(plain(h.context.materials.map((m) => m.id)), [7]); assert.equal(h.context.total, 60);
    h.context.getMaterial = async () => ({ ...details, user_id: 12 }); await h.api.openEditor(9); assert.match(h.alerts.at(-1)[1], /当前用户/);
  });
  await test('title-only editing preserves all other server fields', async () => {
    const h = harness(); h.api.updateDraft({ title: 'Changed' }); await h.api.save();
    assert.deepEqual(plain(h.calls.find((c) => c[0] === 'update')), ['update', 7, { title: 'Changed' }]);
  });
  await test('address edits clear obsolete hierarchy metadata', async () => {
    const h = harness(); h.api.updateDraft({ address: 'New address' }); await h.api.save();
    assert.deepEqual(plain(h.calls[0][2]), { address: 'New address', address_expected_text: null });
  });
  await test('new materials include publishable category, shipping, image and numeric price fields', async () => {
    const h = harness(); h.api.openNew(); h.api.updateDraft({ title: 'New', description: 'Description', price: '20.5', images: ['/static/new.jpg'] });
    h.api.chooseCategory({ cat_id: '123', cat_name: 'Category', channel_cat_id: '456', path: [{ id: '123', name: 'Category' }] }); await h.api.save();
    const payload = h.calls.find((c) => c[0] === 'create')[1]; assert.equal(payload.price, 20.5); assert.equal(payload.platform_category_id, '123');
    assert.equal(payload.platform_channel_category_id, '456'); assert.equal(payload.shipping_method, 'free'); assert.equal(payload.quantity, 1); assert.equal(payload.postage, 0); assert.deepEqual(plain(payload.images), ['/static/new.jpg']);
  });
  await test('invalid price and empty images cannot submit', async () => {
    const h = harness(); h.api.updateDraft({ price: 'NaN' }); await h.api.save(); h.api.updateDraft({ price: '12', images: [] }); await h.api.save();
    assert.equal(h.calls.length, 0); assert.equal(h.alerts.length, 2);
  });
  await test('duplicate save clicks send only one update', async () => {
    const h = harness(); let release; h.context.updateMaterial = () => { h.calls.push(['update']); return new Promise((resolve) => { release = resolve; }); };
    h.api.updateDraft({ price: '30' }); const first = h.api.save(); await h.api.save(); assert.equal(h.calls.length, 1); release(); await first;
  });
  await test('cancelled upload cannot populate another editor', async () => {
    const h = harness(); let release; h.context.uploadProductImages = () => new Promise((resolve) => { release = resolve; });
    const pending = h.api.pickImages(); await new Promise(setImmediate); assert.equal(typeof release, 'function');
    h.api.closeEditor(); h.api.openNew(); release({ urls: ['/stale.jpg'] }); await pending;
    assert.equal(h.context.editor.draft.images.length, 0);
  });
  await test('deletion needs confirmation and checks ownership again', async () => {
    const h = harness(); h.api.confirmDelete(7, 'Original'); assert.equal(h.calls.length, 0);
    h.context.getMaterial = async () => ({ ...details, user_id: 12 }); await h.alerts[0][2].find((b) => b.style === 'destructive').onPress(); assert.equal(h.calls.length, 0);
    h.context.getMaterial = async () => details; h.api.confirmDelete(7, 'Original'); await h.alerts.at(-1)[2].find((b) => b.style === 'destructive').onPress(); assert.deepEqual(h.calls[0], ['delete', 7]);
  });
  await test('relative images resolve against the configured server', () => {
    const h = harness(); assert.equal(h.api.previewUrl('/static/a.jpg', 'https://server.test/'), 'https://server.test/static/a.jpg');
    assert.equal(h.api.previewUrl('https://cdn.test/a.jpg', 'https://server.test'), 'https://cdn.test/a.jpg');
  });
  await test('menu, product tab and material routes match requested behavior', () => {
    const menu = read('xianyu-mobile/app/(tabs)/mine/index.tsx').split('const menuSections: MenuSection[] = [')[1]; assert.equal(menu.match(/title: '([^']+)'/)[1], '商品与推广');
    assert.deepEqual([...menu.matchAll(/label: '([^']+)'/g)].slice(0, 11).map((m) => m[1]), ['商品发布', '商品管理', 'AI 上架', 'AI 配置', '爬虫任务', '上新监控', '监控分类', '监控日志', '兜底账号', '上架历史', '共享扫码']);
    const products = read('xianyu-mobile/app/(tabs)/products/index.tsx'); assert.match(products, /import ItemsScreen from '\.\.\/mine\/items'/); assert.match(products, /<ItemsScreen\s*\/>/); assert.doesNotMatch(products, /Redirect|getMonitoredItems|MonitorTab/);
    assert.ok(read('xianyu-mobile/app/(tabs)/mine/items.tsx').includes("pathname: '/(tabs)/mine/item-edit'"));
    const layout = read('xianyu-mobile/app/(tabs)/mine/_layout.tsx');
    assert.ok(layout.includes('name="materials"'));
    const screens = [...layout.matchAll(/<Stack.Screen name="([^"]+)"/g)].map((m) => m[1]);
    assert.equal(new Set(screens).size, screens.length, 'stack screen names must be unique');
    assert.ok(publishSource.includes("params: { create: '1' }")); assert.ok(publishSource.includes('params: { editId: String(material.id) }'));
    assert.match(publishSource, /useFocusEffect\(useCallback\(\(\) => \{\s*void loadOptions\(\)/);
  });
  console.log(passed + ' materials checks passed; no platform calls made.');
})().catch((error) => { console.error(error); process.exitCode = 1; });
