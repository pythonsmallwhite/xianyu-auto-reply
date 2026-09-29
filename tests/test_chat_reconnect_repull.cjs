/**
 * 在线聊天(新)：重连补偿拉取与发送结果作用域隔离的离线回归。
 *
 * 直接抽取 ChatNew.tsx 中的 mergeConversations / mergeMessages / applySentMessage
 * 与 useChatNewWs.ts 的连接管理逻辑，在受控上下文里验证：
 *   - 重连补拉必须合并而非覆盖（不丢已翻页历史、不重置分页游标）
 *   - 迟到响应不得跨账号/跨会话写入
 *   - 重连才触发补拉，首次连接不触发
 * 不代表真机或浏览器端联调验收。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');

const CHAT_NEW = path.join(__dirname, '../frontend/src/pages/chat-new/ChatNew.tsx');
const WS_HOOK = path.join(__dirname, '../frontend/src/pages/chat-new/useChatNewWs.ts');

/** 从 TSX/TS 源文件中按变量名抽取初始化表达式 */
function extract(source, names) {
  const tree = ts.createSourceFile('x.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found = {};
  const walk = (node) => {
    if (ts.isVariableDeclaration(node) && node.initializer) {
      const name = node.name.getText(tree);
      if (names.includes(name)) found[name] = node.initializer.getText(tree);
    }
    ts.forEachChild(node, walk);
  };
  walk(tree);
  return found;
}

const chatSource = fs.readFileSync(CHAT_NEW, 'utf8');
// applySentMessage 依赖 appendMsg → mergeMessages 与 updateConvList，必须一起注入
const REQUIRED = ['mergeConversations', 'updateConvList', 'mergeMessages', 'appendMsg', 'applySentMessage'];
const extracted = extract(chatSource, REQUIRED);
for (const name of REQUIRED) {
  assert.ok(extracted[name], `未在 ChatNew.tsx 中找到 ${name}`);
}

const conv = (cid) => ({ cid, rawCid: cid, otherUserId: `u-${cid}`, otherUserName: 'n', otherUserAvatar: '', itemTitle: '', lastMessageSummary: '', lastMessageTime: 0, unreadCount: 0 });
const msg = (id, text, extra = {}) => ({ messageId: id, senderId: 'peer', senderName: '', isSelf: false, type: 'text', text, images: [], time: 1000, ...extra });

function createChatHarness() {
  const messagesWrites = [];
  const convWrites = [];
  const context = {
    useCallback: (fn) => fn,
    activeAccountIdRef: { current: 'acc1' },
    activeCidRef: { current: 'c1' },
    convsCacheRef: { current: {} },
    msgsCacheRef: { current: {} },
    setMessages: (value) => messagesWrites.push(value),
    setConversations: (value) => convWrites.push(value),
    isPureDigits: (name) => /^\d+$/.test(name),
  };
  vm.createContext(context);
  // 按依赖顺序注入：mergeMessages → appendMsg → applySentMessage
  const code = ts.transpileModule(
    ['mergeConversations', 'updateConvList', 'mergeMessages', 'appendMsg', 'applySentMessage']
      .map((name) => `globalThis.${name} = ${extracted[name]};`)
      .join('\n'),
    { compilerOptions: { target: ts.ScriptTarget.ES2020 } },
  ).outputText;
  vm.runInContext(code, context);
  return {
    context,
    messagesWrites,
    convWrites,
    // 取出最近一次 setMessages 更新函数并应用到给定列表（归一化为宿主数组）
    applyMessages: (prev) => {
      const update = messagesWrites.at(-1);
      return Array.from(typeof update === 'function' ? update(prev) : update);
    },
    applyConversations: (prev) => {
      const update = convWrites.at(-1);
      return Array.from(typeof update === 'function' ? update(prev) : update);
    },
    mergeMessages: (...args) => Array.from(context.mergeMessages(...args)),
    mergeConversations: (...args) => Array.from(context.mergeConversations(...args)),
  };
}

(async () => {
  // 1. 重连补拉合并会话列表：不得丢掉已经翻页加载的更早会话
  {
    const h = createChatHarness();
    const paged = [conv('c3'), conv('c2')];   // 用户已翻页加载的更早会话
    const fresh = [conv('c1'), conv('c3')];   // 补拉返回的第一页（c3 有新消息被置顶）
    const merged = h.mergeConversations(paged, fresh);
    assert.deepEqual(
      merged.map((c) => c.cid),
      ['c1', 'c3', 'c2'],
      '补拉必须保留已翻页的会话，且不与新数据重复',
    );
  }

  // 2. 重连补拉合并消息：新消息按 id 追加，已加载历史不受影响
  {
    const h = createChatHarness();
    const loaded = [msg('h1', 'old'), msg('m1', 'hi')];
    const latest = [msg('m1', 'hi'), msg('m2', 'new'), msg('m3', 'newer')];
    assert.deepEqual(
      h.mergeMessages(loaded, latest, 'append').map((m) => m.messageId),
      ['h1', 'm1', 'm2', 'm3'],
      '补拉必须去重并追加，不能覆盖已加载历史',
    );
  }

  // 3. 迟到响应：发起时的会话已不是当前会话时必须写缓存，不得串会话
  {
    const h = createChatHarness();
    h.context.activeCidRef.current = 'c2';   // 用户已切换到另一个会话
    h.context.msgsCacheRef.current.acc1 = { c1: { msgs: [msg('h1', 'history')], hasMore: false, cursor: 111 } };
    const sent = msg('s1', 'hello', { isSelf: true, senderId: 'acc1' });
    h.context.applySentMessage('acc1', 'c1', sent, 'hello');
    assert.deepEqual(h.messagesWrites, [], '非当前会话的发送结果不得写入当前消息列表');
    const cached = h.context.msgsCacheRef.current.acc1.c1;
    assert.deepEqual(
      Array.from(cached.msgs, (m) => m.messageId),
      ['h1', 's1'],
      '非当前会话的发送结果必须追加到该会话缓存，且保留已加载历史',
    );
    assert.equal(cached.cursor, 111, '写入结果不得破坏该会话的分页游标');
    assert.equal(h.context.msgsCacheRef.current.acc1.c2, undefined, '不得把结果写到当前会话缓存');
  }

  // 3b. 未打开过的会话没有缓存，此时不得凭空新建只有一条消息的缓存，
  //     否则用户切回该会话时会看不到历史记录
  {
    const h = createChatHarness();
    h.context.activeCidRef.current = 'c2';
    const sent = msg('s9', 'first', { isSelf: true, senderId: 'acc1' });
    h.context.applySentMessage('acc1', 'never_opened', sent, 'first');
    assert.equal(
      h.context.msgsCacheRef.current.acc1?.never_opened,
      undefined,
      '不得为未打开过的会话新建缓存条目',
    );
    assert.deepEqual(h.messagesWrites, [], '不得写入当前消息列表');
  }

  // 4. 迟到响应：账号已切换时同样不得写入当前 state
  {
    const h = createChatHarness();
    h.context.activeAccountIdRef.current = 'acc2';
    h.context.msgsCacheRef.current.acc1 = { c1: { msgs: [], hasMore: true, cursor: null } };
    const sent = msg('s2', 'late', { isSelf: true, senderId: 'acc1' });
    h.context.applySentMessage('acc1', 'c1', sent, 'late');
    assert.deepEqual(h.messagesWrites, [], '跨账号的迟到结果不得写入当前消息列表');
    assert.deepEqual(h.convWrites, [], '跨账号的迟到结果不得写入当前会话列表');
    assert.deepEqual(
      Array.from(h.context.msgsCacheRef.current.acc1.c1.msgs, (m) => m.messageId),
      ['s2'],
      '跨账号结果只能写回原账号缓存',
    );
  }

  // 5. 仍是当前会话时正常写入，并只在成功时更新会话摘要
  {
    const h = createChatHarness();
    const sent = msg('s3', 'ok', { isSelf: true, senderId: 'acc1' });
    h.context.applySentMessage('acc1', 'c1', sent, 'ok');
    assert.deepEqual(h.applyMessages([]).map((m) => m.messageId), ['s3'], '当前会话必须写入消息列表');
    assert.equal(h.applyConversations([conv('c1')])[0].lastMessageSummary, 'ok');

    const h2 = createChatHarness();
    const failed = msg('', 'fail', { isSelf: true, senderId: 'acc1', failed: true, failReason: 'x' });
    h2.context.applySentMessage('acc1', 'c1', failed, null);
    assert.deepEqual(h2.applyMessages([]).map((m) => m.text), ['fail'], '失败消息仍要展示以便重试');
    assert.deepEqual(
      h2.convWrites,
      [],
      '发送失败不得更新会话列表摘要，避免列表出现一条实际并未发出的文本',
    );
  }

  // 6. WebSocket 连接管理：首次连接不补拉，只有断线重连才补拉
  {
    const wsSource = fs.readFileSync(WS_HOOK, 'utf8');
    assert.match(
      wsSource,
      /const isReconnect = everConnectedRef\.current\.has\(aid\)[\s\S]{0,200}?if \(isReconnect\) onReconnectedRef\.current\?\.\(aid\)/,
      '重连补拉必须在区分首连后触发，否则首次进入会重复拉取',
    );
    assert.match(
      wsSource,
      /const cleanupAccount = useCallback\(\(aid: string\) => \{\s*disposeConnection\(aid\)\s*everConnectedRef\.current\.delete\(aid\)/,
      '移除账号必须同时清除“曾连接”标记，保证再次添加按首次连接处理',
    );
    // 重连路径必须走 disposeConnection（保留标记），否则重连会被误判成首连而永不补拉
    assert.match(
      wsSource,
      /const connectAccount = useCallback\(\(aid: string\) => \{\s*disposeConnection\(aid\)/,
      'connectAccount 不得清除“曾连接”标记，否则重连补拉永远不触发',
    );
    assert.match(
      wsSource,
      /isAuthFailure[\s\S]{0,300}?everConnectedRef\.current\.delete\(aid\)/,
      '鉴权失败终止连接时必须清除标记，避免永久停在已连接判定',
    );
  }

  console.log('PASS: chat reconnect re-pull and late-response scoping are isolated');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
