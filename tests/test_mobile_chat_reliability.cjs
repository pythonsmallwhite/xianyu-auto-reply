/**
 * Android 聊天：消息合并与重连补拉的离线回归。
 *
 * 抽取 xianyu-mobile 的两处真实实现，在受控环境里验证移动端聊天可靠性：
 *   A. `app/(tabs)/messages/[id].tsx` 的 mergeMessages / isLocalMessage /
 *      isEchoOf —— 稳定 messageId 合并、本地乐观占位被真实回声吸收、
 *      连发相同内容不丢消息、刷新不冲掉发送中占位、历史分页不重复。
 *   B. `lib/ws.ts` 的 WsManager —— 仅重连触发补拉、首连不触发、
 *      认证失败与主动断开清除“曾连接”标记、多账号互不串扰。
 *
 * 通过 ts.transpileModule + vm 直接执行真实源码，不做逻辑重写；
 * 仅替换网络与存储等外部依赖。不代表真机、Expo 构建或真机验收。
 *
 * 可用 MOBILE_CHAT_ONLY=A1 等环境变量单独运行某条场景，便于改动前后对照。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../xianyu-mobile/node_modules/typescript');

const DETAIL_TSX = path.join(__dirname, '../xianyu-mobile/app/(tabs)/messages/[id].tsx');
const LIST_TSX = path.join(__dirname, '../xianyu-mobile/app/(tabs)/messages/index.tsx');
const WS_TS = path.join(__dirname, '../xianyu-mobile/lib/ws.ts');

const only = process.env.MOBILE_CHAT_ONLY || '';
const results = [];
function scenario(id, title, fn) {
  if (only && only !== id) return;
  try {
    fn();
    results.push({ id, title, ok: true });
  } catch (e) {
    results.push({ id, title, ok: false, error: e.message });
  }
}

// ---------------------------------------------------------------------------
// A. [id].tsx —— 消息合并
// ---------------------------------------------------------------------------

const detailSource = fs.readFileSync(DETAIL_TSX, 'utf8');
const detailTree = ts.createSourceFile(
  '[id].tsx',
  detailSource,
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
);

/** 抽取顶层函数声明与常量初始化表达式（合并逻辑都是模块级函数） */
const capturedFns = {};
const capturedConsts = {};
const walkUntil = (node) => {
  if (ts.isFunctionDeclaration(node) && node.name && node.body) {
    capturedFns[node.name.getText(detailTree)] = node.getText(detailTree);
  }
  if (ts.isVariableDeclaration(node) && node.initializer) {
    capturedConsts[node.name.getText(detailTree)] = node.initializer.getText(detailTree);
  }
  ts.forEachChild(node, walkUntil);
};
walkUntil(detailTree);

const NEEDED_FNS = ['isLocalMessage', 'isEchoOf', 'mergeMessages'];
for (const name of NEEDED_FNS) {
  assert.ok(capturedFns[name], `未在 [id].tsx 中找到函数 ${name}`);
}
const NEEDED_CONSTS = ['LOCAL_MSG_PREFIX', 'LOCAL_ECHO_WINDOW_MS'];
for (const name of NEEDED_CONSTS) {
  assert.ok(capturedConsts[name], `未在 [id].tsx 中找到常量 ${name}`);
}

const mergePrelude = [
  `const LOCAL_MSG_PREFIX = ${capturedConsts.LOCAL_MSG_PREFIX};`,
  `const LOCAL_ECHO_WINDOW_MS = ${capturedConsts.LOCAL_ECHO_WINDOW_MS};`,
  capturedFns.isLocalMessage,
  capturedFns.isEchoOf,
  capturedFns.mergeMessages,
].join('\n');

// 抽取出的片段仍带 TS 类型注解，必须在 vm 执行前转译（不能用 eval 直接跑 TS）
const mergeJs = ts.transpileModule(mergePrelude, {
  compilerOptions: {
    module: ts.ModuleKind.None,
    target: ts.ScriptTarget.ES2020,
    removeComments: false,
  },
}).outputText;

const mergeCtx = vm.createContext({});
vm.runInContext(mergeJs, mergeCtx);
const mergeMessages = (existing, incoming) =>
  // 跨 realm 数组的原型不同，deepStrictEqual 会误判，统一在本 realm 重建
  Array.from(mergeCtx.mergeMessages(Array.from(existing), Array.from(incoming)));

const msg = (over = {}) => ({
  messageId: 'm1',
  senderId: 'self',
  senderName: '我',
  isSelf: true,
  type: 'text',
  text: '你好',
  images: [],
  time: 1_000_000,
  ...over,
});

scenario('A1', '相同 messageId 不重复追加（推送与补拉交错）', () => {
  const existing = [msg({ messageId: 'm1', text: '在吗' })];
  const incoming = [msg({ messageId: 'm1', text: '在吗' })];
  const merged = mergeMessages(existing, incoming);
  assert.equal(merged.length, 1, '同一 messageId 必须只保留一条');
});

scenario('A2', '本地乐观占位被真实回声原地吸收，不出现两条', () => {
  const local = msg({ messageId: 'local-1700000000000', time: 1_000_000 });
  const real = msg({ messageId: 'plat-1', time: 1_000_500 });
  const merged = mergeMessages([local], [real]);
  assert.equal(merged.length, 1, '本地占位 + 真实回声必须合并为一条');
  assert.equal(merged[0].messageId, 'plat-1', '应保留带平台 ID 的真实消息');
});

scenario('A3', '连发两条相同内容不被误合并（各自不同平台 ID）', () => {
  const existing = [msg({ messageId: 'plat-1', time: 1_000_000 })];
  const incoming = [msg({ messageId: 'plat-1', time: 1_000_000 })];
  const merged = mergeMessages(existing, incoming);
  assert.equal(merged.length, 1, 'id 相同才是重复');
  // 不同 id 的相同文本必须都保留：这是“不要用同文字五秒内去重”的核心约束
  const two = mergeMessages(
    [msg({ messageId: 'plat-1', text: '好的', time: 1_000_000 })],
    [msg({ messageId: 'plat-2', text: '好的', time: 1_000_800 })],
  );
  assert.equal(two.length, 2, '不同平台 ID 的相同文本是两条真实消息，不能去重');
});

scenario('A4', '历史占位不被无回声的刷新删除（发送中消息保留）', () => {
  const local = msg({ messageId: 'local-1700000000001', text: '发送中' });
  const older = msg({ messageId: 'plat-0', text: '历史', time: 900_000 });
  // 刷新返回服务端最新页，不含仍在发送中的本地占位
  const merged = mergeMessages([older, local], [older]);
  const ids = merged.map((m) => m.messageId);
  assert.ok(ids.includes('local-1700000000001'), '刷新不得冲掉发送中的本地占位');
  assert.equal(merged.length, 2, '已有历史消息不能被重复插入');
});

scenario('A5', '历史分页头部插入不重复且顺序稳定', () => {
  const existing = [msg({ messageId: 'm2', time: 2_000_000 })];
  const earlier = [msg({ messageId: 'm1', time: 1_000_000 })];
  const merged = mergeMessages(earlier, existing);
  assert.deepEqual(
    Array.from(merged).map((m) => m.messageId),
    ['m1', 'm2'],
    '更早的消息应排在前面且不丢已有消息',
  );
  // 同一页被并发重复触发时不得重复插入
  const again = mergeMessages(earlier, merged);
  assert.deepEqual(
    Array.from(again).map((m) => m.messageId),
    ['m1', 'm2'],
    '重复拉取同一页不得插重',
  );
});

scenario('A6', '他人消息不参与占位吸收，超出窗口不吸收', () => {
  const otherEcho = msg({ messageId: 'plat-9', isSelf: false, senderId: 'buyer' });
  const merged = mergeMessages([], [otherEcho]);
  assert.equal(merged.length, 1);
  // 本地占位 + 时间相差很大的同文本真实消息（非回声）应各自保留
  const staleLocal = msg({ messageId: 'local-1', text: '在的', time: 1_000_000 });
  const farReal = msg({ messageId: 'plat-far', text: '在的', time: 1_000_000 + 60_000 });
  const kept = mergeMessages([staleLocal], [farReal]);
  assert.equal(kept.length, 2, '超出回声窗口的同文本消息不吸收，避免误吞真实消息');
});

// ---------------------------------------------------------------------------
// B. lib/ws.ts —— 重连判别
// ---------------------------------------------------------------------------

/**
 * 把 ws.ts 转成 CJS 后在 vm 中执行
 *
 * 需要替身：react-native（AppState）、@/lib/logger、全局 WebSocket、
 * 定时器（记录回调以便手动推进，不依赖真实时钟）。
 */
function createWsHarness() {
  const compiled = ts.transpileModule(fs.readFileSync(WS_TS, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;

  const sockets = [];
  let wsSeq = 0;
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = FakeWebSocket.CONNECTING;
      this.sent = [];
      this.instanceId = ++wsSeq;
      sockets.push(this);
    }
    send(payload) {
      this.sent.push(payload);
    }
    close() {
      this.readyState = FakeWebSocket.CLOSED;
      this.onclose?.({ code: 1000, reason: 'client close' });
    }
  }
  FakeWebSocket.CONNECTING = 0;
  FakeWebSocket.OPEN = 1;
  FakeWebSocket.CLOSING = 2;
  FakeWebSocket.CLOSED = 3;

  const timeouts = [];
  const intervals = [];
  const logs = [];
  const appStateHandlers = [];

  const logger = {
    info: (...a) => logs.push(['info', ...a]),
    warn: (...a) => logs.push(['warn', ...a]),
    error: (...a) => logs.push(['error', ...a]),
    debug: (...a) => logs.push(['debug', ...a]),
  };

  const moduleShim = { exports: {} };
  const sandbox = {
    module: moduleShim,
    exports: moduleShim.exports,
    require: (id) => {
      if (id === 'react-native') {
        return {
          AppState: {
            addEventListener: (_event, handler) => {
              appStateHandlers.push(handler);
              return { remove: () => {} };
            },
          },
        };
      }
      if (id === '@/lib/logger') return { logger };
      throw new Error(`未预期的模块依赖: ${id}`);
    },
    console,
    Promise,
    Map,
    Set,
    WebSocket: FakeWebSocket,
    setTimeout: (fn, delay) => {
      const handle = { fn, delay, kind: 'timeout' };
      timeouts.push(handle);
      return handle;
    },
    clearTimeout: (handle) => {
      const idx = timeouts.indexOf(handle);
      if (idx >= 0) timeouts.splice(idx, 1);
    },
    setInterval: (fn, delay) => {
      const handle = { fn, delay, kind: 'interval' };
      intervals.push(handle);
      return handle;
    },
    clearInterval: (handle) => {
      const idx = intervals.indexOf(handle);
      if (idx >= 0) intervals.splice(idx, 1);
    },
  };
  sandbox.globalThis = sandbox;
  const ctx = vm.createContext(sandbox);
  vm.runInContext(compiled, ctx);
  const manager = moduleShim.exports.wsManager;
  assert.ok(manager, 'ws.ts 未导出 wsManager');

  return {
    manager,
    sockets,
    logs,
    /** 让最新建立的连接握手成功 */
    openLatest() {
      const ws = sockets[sockets.length - 1];
      assert.ok(ws, '没有可用连接');
      ws.readyState = FakeWebSocket.OPEN;
      ws.onopen?.();
      return ws;
    },
    /** 模拟服务端/网络断开（非认证失败） */
    dropLatest(code = 1006) {
      const ws = sockets[sockets.length - 1];
      ws.readyState = FakeWebSocket.CLOSED;
      ws.onclose?.({ code, reason: 'drop' });
      return ws;
    },
    /** 推进最近一次的自动重连定时器 */
    fireReconnect() {
      const pending = timeouts.filter((t) => t.kind === 'timeout');
      assert.ok(pending.length > 0, '没有待触发的重连定时器');
      const latest = pending[pending.length - 1];
      clearTimeoutImpl(latest);
      latest.fn();
    },
    fireAppState(state) {
      appStateHandlers.forEach((fn) => fn(state));
    },
    pingLatest() {
      const ws = sockets[sockets.length - 1];
      return ws.sent.map((s) => JSON.parse(s)).filter((p) => p.type === 'ping');
    },
  };
  function clearTimeoutImpl(handle) {
    const idx = timeouts.indexOf(handle);
    if (idx >= 0) timeouts.splice(idx, 1);
  }
}

function setupWs() {
  const h = createWsHarness();
  h.manager.configure('http://127.0.0.1:8000', 'tok');
  const events = [];
  h.manager.onReconnected((accountId) => events.push(accountId));
  return { ...h, events };
}

scenario('B1', '首次建连不触发补拉（避免与首屏加载重复请求）', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  assert.deepEqual(h.events, [], '首次连接不应触发补拉');
});

scenario('B2', '掉线自动重连成功后触发补拉', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  h.dropLatest();
  h.fireReconnect();
  h.openLatest();
  assert.deepEqual(h.events, ['acc-1'], '重连成功必须通知补拉');
});

scenario('B3', '认证失败清除标记，下次建连按首次处理', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  // 4401：服务端判定鉴权失败，不再重连
  const ws = h.sockets[h.sockets.length - 1];
  ws.readyState = 3;
  ws.onclose?.({ code: 4401, reason: 'unauthorized' });
  assert.equal(h.events.length, 0, '认证失败本身不触发补拉');
  // 重新登录后再次建连：应视为首次连接，不触发补拉
  h.manager.connect('acc-1');
  h.openLatest();
  assert.deepEqual(h.events, [], '认证失败后重建连应按首次处理');
});

scenario('B4', '主动断开（切账号/离开页面）清除标记', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  h.manager.disconnect('acc-1');
  h.manager.connect('acc-1');
  h.openLatest();
  assert.deepEqual(h.events, [], '主动断开后重建连不应算重连');
});

scenario('B5', '多账号重连互不串扰', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  h.manager.connect('acc-2');
  h.openLatest();
  // 仅 acc-1 掉线并恢复
  const first = h.sockets[0];
  first.readyState = 3;
  first.onclose?.({ code: 1006, reason: 'drop' });
  h.fireReconnect();
  h.openLatest();
  assert.deepEqual(h.events, ['acc-1'], '只应通知真正重连的账号');
});

scenario('B6', '前台恢复触发的重连也触发补拉', () => {
  const h = setupWs();
  h.manager.connect('acc-1');
  h.openLatest();
  // 模拟重试耗尽后 WS 处于关闭态，App 回到前台时管理器自行重建
  const ws = h.sockets[h.sockets.length - 1];
  ws.readyState = 3;
  h.fireAppState('active');
  h.openLatest();
  assert.deepEqual(h.events, ['acc-1'], '前台恢复重建连接同样需要补拉');
});

// ---------------------------------------------------------------------------
// C. [id].tsx —— 调用点契约
//
// A4/A5 验证的是 mergeMessages 自身的语义；即使把调用点退回“整体替换”
// （setMessages(resp.messages)）它们仍会通过，因为那条路径绕过了合并函数。
// 因此这里额外对调用点做源码级断言，锁住“刷新/分页必须走合并”的契约，
// 与 tests/test_chat_reconnect_repull.cjs 对 useChatNewWs.ts 的做法一致。
// ---------------------------------------------------------------------------

scenario('C1', '刷新与分页调用点必须走 mergeMessages 而非整体替换', () => {
  const src = detailSource;
  assert.ok(
    !/setMessages\(\s*resp\.messages\s*\)/.test(src),
    '刷新不得用 setMessages(resp.messages) 整体替换，会冲掉发送中的本地占位',
  );
  assert.ok(
    !/setMessages\(\(prev\)\s*=>\s*\[\s*\.\.\.resp\.messages\s*,\s*\.\.\.prev\s*\]\)/.test(src),
    '分页不得直接拼接 resp.messages，需经 mergeMessages 按稳定 ID 去重',
  );
  assert.ok(
    /setMessages\(\(prev\)\s*=>\s*mergeMessages\(resp\.messages,\s*prev\)\)/.test(src),
    '分页需调用 mergeMessages(resp.messages, prev)',
  );
  assert.ok(
    /setMessages\(\(prev\)\s*=>\s*mergeMessages\(prev,\s*resp\.messages\)\)/.test(src),
    '刷新需调用 mergeMessages(prev, resp.messages)',
  );
});

scenario('C2', 'WS 推送与重连补拉走同一套稳定 ID 合并', () => {
  const src = detailSource;
  assert.ok(
    /setMessages\(\(prev\)\s*=>\s*mergeMessages\(prev,\s*\[message\]\)\)/.test(src),
    'WS 消息需经 mergeMessages 合并，不能无脑追加导致自己发的消息重复',
  );
  assert.ok(
    /wsManager\.onReconnected\(/.test(src) &&
      /accountId\s*!==\s*account_id/.test(src),
    '需订阅重连事件并按账号过滤后再补拉',
  );
  // 补拉不得污染分页游标
  const syncBody = src.slice(src.indexOf('const syncLatest'), src.indexOf('useEffect', src.indexOf('const syncLatest')));
  assert.ok(
    !/cursorRef\.current\s*=/.test(syncBody) && !/hasMoreRef\.current\s*=/.test(syncBody),
    '补拉只对齐最新页，不得改写 cursorRef/hasMoreRef',
  );
});

scenario('C3', '发送中不禁用输入框，也不在发送期间收起键盘', () => {
  const src = detailSource;
  const inputBlock = src.slice(src.indexOf('placeholder="输入消息..."'));
  const textInputEnd = inputBlock.indexOf('/>');
  const inputTag = inputBlock.slice(0, textInputEnd < 0 ? 900 : textInputEnd);
  assert.ok(
    !/editable=\{!sending\}/.test(inputTag),
    '发送期间禁用输入会收起键盘并中断连续输入，应仅由发送按钮拦截并发',
  );
});

scenario('C4', '分页入口随 hasMore 消失，且滚动跟随以贴底为条件', () => {
  const src = detailSource;
  assert.ok(
    /hasMore\s*&&\s*messages\.length\s*>\s*0/.test(src),
    '“加载更早的消息”入口需依赖 state 形式的 hasMore，否则分页耗尽后不会消失',
  );
  assert.ok(
    /atBottomRef\.current/.test(src),
    '需按是否贴底决定是否自动滚动，否则上翻历史会被新消息拉回底部',
  );
  assert.ok(
    /setHasMore\(resp\.hasMore\)/.test(src),
    'hasMore 需同步写入 state 才能驱动界面更新',
  );
});

// ---------------------------------------------------------------------------
// D. messages/index.tsx —— 会话列表合并
// ---------------------------------------------------------------------------

const listSource = fs.readFileSync(LIST_TSX, 'utf8');
const listTree = ts.createSourceFile('index.tsx', listSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

let capturedMergeConversations = null;
let capturedConvLimit = null;
const walkList = (node) => {
  if (ts.isFunctionDeclaration(node) && node.name?.getText(listTree) === 'mergeConversations' && node.body) {
    capturedMergeConversations = node.getText(listTree);
  }
  if (ts.isVariableDeclaration(node) && node.name.getText(listTree) === 'CONV_CACHE_LIMIT' && node.initializer) {
    capturedConvLimit = node.initializer.getText(listTree);
  }
  ts.forEachChild(node, walkList);
};
walkList(listTree);
assert.ok(capturedMergeConversations, '未在 messages/index.tsx 中找到 mergeConversations');
assert.ok(capturedConvLimit, '未在 messages/index.tsx 中找到 CONV_CACHE_LIMIT');

const convCtx = vm.createContext({});
vm.runInContext(
  ts.transpileModule(
    `const CONV_CACHE_LIMIT = ${capturedConvLimit};\n${capturedMergeConversations}`,
    { compilerOptions: { module: ts.ModuleKind.None, target: ts.ScriptTarget.ES2020 } },
  ).outputText,
  convCtx,
);
const mergeConversations = (prev, incoming, mode) =>
  Array.from(convCtx.mergeConversations(Array.from(prev), Array.from(incoming), mode));

const conv = (cid, over = {}) => ({
  cid,
  rawCid: cid,
  otherUserId: `u-${cid}`,
  otherUserName: `买家${cid}`,
  otherUserAvatar: '',
  itemTitle: '',
  lastMessageSummary: '你好',
  lastMessageTime: 1_000_000,
  unreadCount: 0,
  ...over,
});

scenario('D1', '刷新（重连补拉）保留已翻页加载的旧会话', () => {
  // 用户已翻到第 2 页，列表含 c1/c3/c2
  const prev = [conv('c1'), conv('c3'), conv('c2')];
  // 补拉只返回最新一页
  const incoming = [conv('c1', { lastMessageSummary: '最新一条' })];
  const merged = mergeConversations(prev, incoming, 'refresh');
  assert.deepEqual(
    Array.from(merged).map((x) => x.cid),
    ['c1', 'c3', 'c2'],
    '补拉不得丢掉已翻页的会话，且最新页在前',
  );
  assert.equal(merged[0].lastMessageSummary, '最新一条', '同 cid 应以服务端最新字段为准');
});

scenario('D2', '分页追加按 cid 去重且不重复插入', () => {
  const prev = [conv('c1'), conv('c2')];
  const page2 = [conv('c2'), conv('c3')];
  const merged = mergeConversations(prev, page2, 'append');
  assert.deepEqual(
    Array.from(merged).map((x) => x.cid),
    ['c1', 'c2', 'c3'],
    '追加时重复返回的 c2 不得插重，且更早的页应排在后面',
  );
});

scenario('D3', '本地新建会话不被空结果冲掉', () => {
  const local = conv('c-local', { otherUserName: '新买家' });
  const merged = mergeConversations([local], [], 'refresh');
  assert.deepEqual(Array.from(merged).map((x) => x.cid), ['c-local']);
});

scenario('D4', '合并结果受上限约束，避免长列表无限增长', () => {
  const prev = Array.from({ length: 250 }, (_, i) => conv(`old-${i}`));
  const merged = mergeConversations(prev, [conv('new-1')], 'refresh');
  assert.ok(merged.length <= 200, `合并后长度应受上限约束，实际 ${merged.length}`);
  assert.equal(merged[0].cid, 'new-1', '最新会话必须保留在首位');
});

scenario('D5', '重连补拉必须走合并而非整体替换（调用点契约）', () => {
  assert.ok(
    !/setConversations\(resp\.conversations\)/.test(listSource),
    '刷新不得用 setConversations(resp.conversations) 整体替换，会丢掉已翻页会话',
  );
  assert.ok(
    /mergeConversations\(prev,\s*resp\.conversations,\s*'refresh'\)/.test(listSource),
    '刷新需调用 mergeConversations(prev, resp.conversations, "refresh")',
  );
  assert.ok(
    /mergeConversations\(prev,\s*resp\.conversations,\s*'append'\)/.test(listSource),
    '分页需调用 mergeConversations(prev, resp.conversations, "append")',
  );
  assert.ok(
    /wsManager\.onReconnected\(/.test(listSource) &&
      /reconnectedId\s*!==\s*accountId/.test(listSource),
    '会话列表需订阅重连事件并按账号过滤后再补拉',
  );
});

// ---------------------------------------------------------------------------

const failed = results.filter((r) => !r.ok);
for (const r of results) {
  console.log(`${r.ok ? 'PASS' : 'FAIL'} [${r.id}] ${r.title}`);
  if (!r.ok) console.log(`      ${r.error}`);
}
if (failed.length > 0) {
  console.error(`\n${failed.length}/${results.length} 场景失败`);
  process.exit(1);
}
console.log(`\nPASS: android chat message merge and reconnect re-pull are isolated (${results.length} 场景)`);
