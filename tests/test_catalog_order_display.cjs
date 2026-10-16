// Execute real TSX components, hooks and events with offline DOM/API substitutes.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');
const root = path.resolve(__dirname, '../frontend/src');
const itemFile = 'pages/items/Items.tsx';
const orderFile = 'pages/orders/Orders.tsx';
const thumbnailFile = 'pages/items/ItemThumbnail.tsx';
const plain = value => JSON.parse(JSON.stringify(value));
const sampleItem = { id: 1, cookie_id: 'offline-account', item_id: 'item-1', item_title: '测试商品', source_category: 'managed', item_images: ['https://offline.invalid/first.jpg', 'https://offline.invalid/second.jpg'] };
const sampleOrder = { id: '1', order_id: 'order-1', cookie_id: 'offline-account', item_id: 'item-1', item_title: '很长的商品名称'.repeat(30), buyer_id: 'buyer-1', buyer_fish_nick: '很长的测试昵称'.repeat(30), amount: '10', quantity: 1, status: 'pending_ship' };

function harness(file, props = {}, options = {}) {
  const instances = new Map(), hosts = new Map(), cache = new Map(), observers = [], requests = [], timers = new Map(), calls = [];
  const storage = new Map(Object.entries(options.storage || {}));
  let current, cursor, dirty = true, output, timerId = 0, rootProps = props;
  let items = options.items || [sampleItem], orders = options.orders || [sampleOrder];
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
  const React = {
    useState(initial) {
      const instance = current, index = cursor++;
      if (!(index in instance.slots)) instance.slots[index] = typeof initial === 'function' ? initial() : initial;
      return [instance.slots[index], value => {
        const next = typeof value === 'function' ? value(instance.slots[index]) : value;
        if (!Object.is(next, instance.slots[index])) { instance.slots[index] = next; dirty = true; }
      }];
    },
    useRef(initial) { const index = cursor++; return current.slots[index] ||= { current: initial }; },
    useEffect(fn, deps) {
      const index = cursor++, old = current.effects[index];
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) current.pending.push({ index, fn, deps });
    },
  };
  class Observer {
    constructor(callback) { this.callback = callback; this.active = true; observers.push(this); }
    observe(target) { this.target = target; }
    disconnect() { this.active = false; }
  }
  function host(type) {
    const listeners = new Map();
    let src = '';
    return {
      type, duration: 4, readyState: 2, videoWidth: 640, videoHeight: 480, currentTime: 0, preload: 'none', pauses: 0, loads: 0,
      get src() { return src; },
      set src(value) { src = value; requests.push(value); },
      addEventListener(name, fn) { listeners.set(name, fn); },
      removeEventListener(name) { listeners.delete(name); },
      emit(name) { listeners.get(name)?.(); },
      removeAttribute(name) { if (name === 'src') src = ''; },
      pause() { this.pauses++; },
      load() { this.loads++; },
    };
  }
  const stub = new Proxy({}, { get: (_, name) => name === '__esModule' ? true : String(name) });
  const context = vm.createContext({
    console, URL, URLSearchParams, queueMicrotask,
    IntersectionObserver: options.noObserver ? undefined : Observer,
    localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    setTimeout: fn => { const id = ++timerId; timers.set(id, fn); return id; }, clearTimeout: id => timers.delete(id),
  });
  function load(relative) {
    if (cache.has(relative)) return cache.get(relative);
    const module = { exports: {} };
    cache.set(relative, module.exports);
    const requireOffline = name => {
      if (name === 'react') return React;
      if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx, Fragment: 'Fragment' };
      if (name === './ItemThumbnail') return load(thumbnailFile);
      if (name === 'react-router-dom') return { useSearchParams: () => [new URLSearchParams()] };
      if (name === 'framer-motion') return { motion: { div: 'motion.div' } };
      if (name === '@/store/authStore') return { useAuthStore: () => ({ isAuthenticated: true, token: 'offline', _hasHydrated: true }) };
      if (name === '@/store/uiStore') return { useUIStore: () => ({ addToast: value => calls.push(['toast', value]) }) };
      if (name === '@/api/accounts') return { getAccountDetails: async () => [{ id: 'offline-account' }] };
      if (name === '@/api/items') return { getItemsPaginated: async (...args) => {
        calls.push(['items', ...plain(args)]);
        return { success: true, data: items, page: args[0], page_size: args[1], total: 40, total_pages: 2 };
      } };
      if (name === '@/api/orders') return {
        getOrders: async (...args) => { calls.push(['orders', ...plain(args)]); return { success: true, data: orders, page: args[2], page_size: args[3], total: 40, total_pages: 2 }; },
        getOrderDetail: async id => { calls.push(['detail', id]); return { success: true, data: sampleOrder }; },
      };
      if (name === 'lucide-react' || name.startsWith('@/components/') || name.startsWith('./') || name === '@/api/settings' || name === '@/pages/common/LocationContactReplyFields') return stub;
      throw new Error(`Network/import prohibited: ${name}`);
    };
    const compiled = ts.transpileModule(fs.readFileSync(path.join(root, relative), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInContext(`(function(require, module, exports) { ${compiled} })`, context)(requireOffline, module, module.exports);
    cache.set(relative, module.exports);
    return module.exports;
  }
  const exports = load(file), component = exports.Items || exports.Orders || exports.ItemThumbnail;
  function cleanup(instance) { instance.effects.forEach(effect => effect?.cleanup?.()); }
  function render() {
    let passes = 0;
    do {
      assert.ok(++passes < 30, 'render loop');
      dirty = false;
      const seen = new Set(), seenHosts = new Set();
      function resolve(node, location) {
        if (node == null || typeof node !== 'object') return node;
        if (Array.isArray(node)) return node.map((child, index) => resolve(child, `${location}/${child?.key ?? index}`));
        if (typeof node.type === 'function') {
          const id = `${location}:${node.key ?? ''}`;
          let instance = instances.get(id);
          if (instance && instance.type !== node.type) { cleanup(instance); instances.delete(id); instance = null; }
          if (!instance) { instance = { type: node.type, slots: [], effects: [], pending: [] }; instances.set(id, instance); }
          seen.add(id); current = instance; cursor = 0;
          return resolve(node.type(node.props), `${id}/result`);
        }
        if (node.props.ref) {
          seenHosts.add(location);
          if (!hosts.has(location)) hosts.set(location, host(node.type));
          node.props.ref.current = hosts.get(location);
        }
        return { ...node, props: { ...node.props, children: resolve(node.props.children, `${location}/children`) } };
      }
      output = resolve(jsx(component, rootProps), 'root');
      for (const [id, instance] of instances) if (!seen.has(id)) { cleanup(instance); instances.delete(id); }
      for (const id of hosts.keys()) if (!seenHosts.has(id)) hosts.delete(id);
      for (const instance of instances.values()) {
        for (const next of instance.pending.splice(0)) { instance.effects[next.index]?.cleanup?.(); instance.effects[next.index] = { deps: next.deps, cleanup: next.fn() }; }
      }
    } while (dirty);
  }
  async function flush() { for (let i = 0; i < 6; i++) { await new Promise(resolve => setImmediate(resolve)); if (dirty) render(); } }
  function nodes(start = output) {
    const result = [];
    function visit(node) { if (!node || typeof node !== 'object') return; if (Array.isArray(node)) return node.forEach(visit); result.push(node); visit(node.props.children); }
    visit(start); return result;
  }
  function text(node) { if (node == null || typeof node === 'boolean') return ''; if (Array.isArray(node)) return node.map(text).join(''); return typeof node === 'object' ? text(node.props.children) : String(node); }
  const find = (type, label) => nodes().find(node => node.type === type && (text(node).includes(label) || node.props.title === label));
  async function click(node) { assert.ok(node, 'missing clickable element'); assert.ok(!node.props.disabled); await node.props.onClick(); render(); await flush(); }
  async function change(node, value) { assert.ok(node, 'missing input'); node.props.onChange({ target: { value, checked: value } }); render(); await flush(); }
  render();
  return {
    nodes, text, find, click, change, flush, requests, calls, timers, storage,
    videos: () => [...hosts.values()].filter(element => element.type === 'video'),
    async visible(value = true) { observers.filter(observer => observer.active).forEach(observer => observer.callback([{ isIntersecting: value }])); render(); await flush(); },
    async update(props) { rootProps = props; render(); await flush(); },
    async timeout() { [...timers.values()].forEach(fn => fn()); render(); await flush(); },
    setItems(value) { items = value; }, setOrders(value) { orders = value; },
    unmount() { for (const instance of instances.values()) cleanup(instance); instances.clear(); },
  };
}

let passed = 0;
async function test(name, fn) { await fn(); passed++; console.log(`PASS ${name}`); }
(async () => {
  await test('first image is lazy, bounded, fails to placeholder and resets for new media', async () => {
    const h = harness(thumbnailFile, { item: sampleItem });
    assert.equal(h.nodes().filter(n => n.type === 'img').length, 0);
    await h.visible();
    const image = h.find('img', '');
    assert.equal(image.props.src, sampleItem.item_images[0]);
    assert.equal(image.props.loading, 'lazy'); assert.equal(image.props.width, 48); assert.equal(image.props.height, 48);
    image.props.onError(); await h.flush();
    assert.ok(h.find('span', '加载失败')); assert.equal(h.requests.length, 0);
    await h.update({ item: { ...sampleItem, item_images: ['/static/new.jpg'] } }); await h.visible();
    assert.equal(h.find('img', '').props.src, '/static/new.jpg'); h.unmount();
  });
  await test('cover wins over image and video; broken cover falls back to first image', async () => {
    const h = harness(thumbnailFile, { item: { ...sampleItem, item_video_cover: '//offline.invalid/cover.jpg', item_video_url: 'https://offline.invalid/video.mp4' } });
    await h.visible(); assert.equal(h.find('img', '').props.src, 'https://offline.invalid/cover.jpg');
    assert.equal(h.videos().length, 0); h.find('img', '').props.onError(); await h.flush();
    assert.equal(h.find('img', '').props.src, sampleItem.item_images[0]); assert.equal(h.requests.length, 0); h.unmount();
  });
  await test('missing media and disallowed URLs have honest placeholders', async () => {
    const h = harness(thumbnailFile, { item: { ...sampleItem, item_images: ['javascript:alert(1)'], item_video_url: 'data:video/mp4;base64,no' } });
    await h.visible(); assert.ok(h.find('span', '无媒体')); assert.equal(h.requests.length, 0); h.unmount();
  });
  await test('browser without IntersectionObserver still uses native image lazy loading', async () => {
    const h = harness(thumbnailFile, { item: sampleItem }, { noObserver: true }); await h.flush();
    assert.equal(h.find('img', '').props.loading, 'lazy'); assert.equal(h.requests.length, 0); h.unmount();
  });
  await test('video waits for visibility, seeks a decoded frame and releases on hiding', async () => {
    const h = harness(thumbnailFile, { item: { ...sampleItem, item_images: [], item_video_url: 'https://offline.invalid/first.mp4' } });
    assert.equal(h.requests.length, 0); await h.visible();
    const video = h.videos()[0]; assert.equal(h.requests.length, 1);
    assert.equal(h.find('video', '').props.preload, 'none'); assert.ok(h.find('video', '').props.muted); assert.equal(h.find('video', '').props.autoPlay, undefined);
    video.emit('loadedmetadata'); assert.equal(video.currentTime, 0.1); video.emit('seeked'); await h.flush();
    assert.ok(h.find('span', '视频')); assert.equal(video.preload, 'none'); assert.equal(h.timers.size, 0);
    await h.visible(false); assert.equal(video.src, ''); assert.ok(video.pauses > 0); assert.equal(h.videos().length, 0); h.unmount();
  });
  await test('video errors and timeouts stop downloads and display failure', async () => {
    for (const mode of ['error', 'timeout', 'invalid']) {
      const h = harness(thumbnailFile, { item: { ...sampleItem, item_images: [], item_video_url: 'https://offline.invalid/bad.mp4' } });
      await h.visible(); const video = h.videos()[0];
      if (mode === 'timeout') await h.timeout();
      else if (mode === 'invalid') { video.duration = Infinity; video.emit('loadedmetadata'); }
      else video.emit('error');
      await h.flush(); assert.ok(h.find('span', '加载失败')); assert.equal(video.src, ''); assert.equal(h.timers.size, 0); h.unmount();
    }
  });
  await test('video seek exception uses failure placeholder', async () => {
    const h = harness(thumbnailFile, { item: { ...sampleItem, item_images: [], item_video_url: 'https://offline.invalid/seek.mp4' } });
    await h.visible(); const video = h.videos()[0];
    Object.defineProperty(video, 'currentTime', { set() { throw new Error('unsupported seek'); } });
    video.emit('loadedmetadata'); await h.flush(); assert.ok(h.find('span', '加载失败')); assert.equal(video.src, ''); h.unmount();
  });
  await test('short video seek stays within duration and missing decoded frame is not success', async () => {
    const h = harness(thumbnailFile, { item: { ...sampleItem, item_images: [], item_video_url: 'https://offline.invalid/short.mp4' } });
    await h.visible(); const video = h.videos()[0]; video.duration = 0.05; video.readyState = 1; video.videoWidth = 0;
    video.emit('loadedmetadata'); assert.equal(video.currentTime, 0.025); video.emit('seeked'); await h.flush();
    assert.equal(h.find('span', '视频'), undefined); await h.timeout(); assert.ok(h.find('span', '加载失败')); h.unmount();
  });
  await test('catalog toggle defaults off and preserves page, selection and filtering', async () => {
    const h = harness(itemFile); await h.flush();
    const toggle = () => h.nodes(h.find('label', '显示小图')).find(n => n.type === 'input');
    assert.equal(toggle().props.checked, false); await h.visible(); assert.equal(h.find('img', ''), undefined); assert.equal(h.videos().length, 0);
    const row = h.nodes().find(n => n.type === 'tr' && n.key === 1);
    await h.click(h.nodes(row).find(n => n.type === 'button'));
    const count = h.calls.filter(c => c[0] === 'items').length;
    await h.change(toggle(), true); await h.visible();
    assert.ok(h.find('img', '')); assert.equal(h.calls.filter(c => c[0] === 'items').length, count);
    assert.ok(h.nodes().find(n => n.type === 'tr' && n.key === 1).props.className.includes('bg-blue-50'));
    await h.click(h.nodes().find(n => n.type === 'button' && h.nodes(n).some(child => child.type === 'ChevronRight')));
    assert.equal(h.calls.filter(c => c[0] === 'items').at(-1)[1], 2);
    await h.change(toggle(), false); assert.equal(h.find('img', ''), undefined);
    await h.change(h.nodes().find(n => n.type === 'input' && n.props.placeholder === '搜索商品ID、标题或详情...'), '  商品  ');
    await h.click(h.find('button', '查询'));
    assert.equal(h.calls.filter(c => c[0] === 'items').at(-1)[4].keyword, '商品'); h.unmount();
  });
  await test('catalog empty row spans toggle column correctly', async () => {
    const h = harness(itemFile, {}, { items: [] }); await h.flush();
    assert.equal(h.nodes().find(n => n.type === 'td' && n.props.colSpan).props.colSpan, 16);
    await h.change(h.nodes(h.find('label', '显示小图')).find(n => n.type === 'input'), true);
    assert.equal(h.nodes().find(n => n.type === 'td' && n.props.colSpan).props.colSpan, 17); h.unmount();
  });
  await test('multiple video rows start at most two; disabling cancels all queued URLs', async () => {
    const rows = [1, 2, 3, 4].map(id => ({ ...sampleItem, id, item_images: [], item_video_url: `https://offline.invalid/${id}.mp4` }));
    const h = harness(itemFile, {}, { items: rows }); await h.flush();
    const toggle = () => h.nodes(h.find('label', '显示小图')).find(n => n.type === 'input');
    await h.change(toggle(), true); await h.visible(); assert.equal(h.requests.length, 2);
    const first = h.videos()[0]; first.emit('loadedmetadata'); first.emit('seeked'); await h.flush(); assert.equal(h.requests.length, 3);
    const videos = h.videos(); await h.change(toggle(), false);
    assert.equal(h.requests.length, 3, 'queued fourth video must not start while disabling');
    assert.ok(videos.every(video => video.src === '')); assert.equal(h.timers.size, 0); h.unmount();
  });
  await test('orders render full names above IDs with bounded truncation and title', async () => {
    const h = harness(orderFile); await h.flush();
    for (const [key, name, id, width] of [['item_id', sampleOrder.item_title, sampleOrder.item_id, '240'], ['buyer_id', sampleOrder.buyer_fish_nick, sampleOrder.buyer_id, '180']]) {
      const cell = h.nodes().find(n => n.type === 'td' && n.key === key);
      const fields = h.nodes(cell).filter(n => n.type === 'div' && n.props.title);
      assert.equal(h.text(fields[0]), name); assert.equal(fields[0].props.title, name); assert.ok(fields[0].props.className.includes('truncate'));
      assert.equal(h.text(fields[1]), id); assert.ok(h.nodes(cell).some(n => n.props.className?.includes(`max-w-[${width}px]`)));
    }
    assert.equal(h.nodes().some(n => n.type === 'td' && n.key === 'buyer_fish_nick'), false, 'redundant nickname column defaults hidden');
    assert.ok(h.find('th', '商品')); assert.ok(h.find('th', '买家')); h.unmount();
  });
  await test('orders use missing-name placeholders without inventing identity', async () => {
    const h = harness(orderFile, {}, { orders: [{ ...sampleOrder, item_title: ' ', buyer_fish_nick: null }] }); await h.flush();
    assert.ok(h.find('div', '商品名称暂不可用')); assert.ok(h.find('div', '买家昵称暂不可用'));
    assert.ok(h.nodes().some(n => n.props.title === sampleOrder.buyer_id)); h.unmount();
  });
  await test('order saved columns, selection, detail action, filters and pagination remain usable', async () => {
    const initial = harness(orderFile); await initial.flush();
    await initial.click(initial.nodes().find(n => n.type === 'button' && initial.nodes(n).some(child => child.type === 'Settings')));
    const source = fs.readFileSync(path.join(root, orderFile), 'utf8');
    const ast = ts.createSourceFile(orderFile, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
    const declaration = ast.statements.find(s => ts.isVariableStatement(s) && s.declarationList.declarations.some(d => d.name.getText(ast) === 'defaultColumns')).declarationList.declarations[0];
    const saved = vm.runInNewContext(`(${declaration.initializer.getText(ast)})`);
    saved.find(c => c.key === 'delivery_fail_reason').visible = false; saved.find(c => c.key === 'created_at').visible = true;
    Object.assign(saved.find(c => c.key === 'buyer_fish_nick'), { visible: true, fixed: true });
    saved.find(c => c.key === 'item_id').label = '商品ID'; saved.find(c => c.key === 'buyer_id').label = '买家ID';
    const json = JSON.stringify(saved); initial.unmount();
    const h = harness(orderFile, {}, { storage: { 'order-columns-config': json } }); await h.flush();
    assert.equal(h.nodes().some(n => n.type === 'td' && n.key === 'delivery_fail_reason'), false);
    assert.ok(h.nodes().some(n => n.type === 'td' && n.key === 'created_at')); assert.equal(h.storage.get('order-columns-config'), json);
    assert.equal(h.text(h.nodes().find(n => n.type === 'th' && n.key === 'item_id')), '商品');
    assert.equal(h.text(h.nodes().find(n => n.type === 'th' && n.key === 'buyer_id')), '买家');
    const nickname = h.nodes().find(n => n.type === 'td' && n.key === 'buyer_fish_nick');
    assert.ok(h.nodes(nickname).some(n => n.props.className?.includes('max-w-[180px]') && n.props.title === sampleOrder.buyer_fish_nick));
    const row = h.nodes().find(n => n.type === 'tr' && n.key === sampleOrder.id);
    await h.change(h.nodes(row).find(n => n.type === 'input' && n.props.type === 'checkbox'), true);
    assert.ok(h.nodes().find(n => n.type === 'tr' && n.key === sampleOrder.id).props.className.includes('bg-blue'));
    await h.click(h.find('button', '查看详情')); assert.deepEqual(h.calls.filter(c => c[0] === 'detail')[0], ['detail', sampleOrder.order_id]);
    await h.click(h.find('button', '下一页')); assert.equal(h.calls.filter(c => c[0] === 'orders').at(-1)[3], 2);
    await h.click(h.find('button', '筛选'));
    const search = h.nodes().find(n => n.type === 'input' && n.props.type === 'text' && n.props.placeholder?.includes('订单'));
    await h.change(search, 'buyer-1'); await h.click(h.find('button', '查询'));
    assert.equal(h.calls.filter(c => c[0] === 'orders').at(-1)[5].search, 'buyer-1');
    await h.click(h.nodes().find(n => n.type === 'button' && h.nodes(n).some(child => child.type === 'Settings')));
    const nicknameToggle = h.nodes(h.find('label', '买家昵称')).find(n => n.type === 'input');
    assert.equal(nicknameToggle.props.disabled, false); await h.change(nicknameToggle, false);
    assert.equal(h.nodes().some(n => n.type === 'td' && n.key === 'buyer_fish_nick'), false);
    assert.equal(JSON.parse(h.storage.get('order-columns-config')).find(c => c.key === 'buyer_fish_nick').visible, false); h.unmount();
  });
  console.log(`${passed} catalog/order behavior tests passed; no real network requests.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
