const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');

const source = fs.readFileSync(
  path.join(__dirname, '../frontend/src/pages/chat-new/chat_history_recovery.ts'),
  'utf8',
).replace(/^import[^\n]*\n/gm, '').replace(/export /g, '');
const mergeSource = fs.readFileSync(
  path.join(__dirname, '../frontend/src/pages/chat-new/chat_history_merge.ts'),
  'utf8',
).replace(/^import[^\n]*\n/gm, '').replace(/export /g, '');
const code = ts.transpileModule(
  `${mergeSource}\n${source}\nglobalThis.recoverMessages = recoverMessages;\nglobalThis.recoverConversations = recoverConversations;`,
  { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None } },
).outputText;
const vm = require('node:vm');
const context = {};
vm.createContext(context);
vm.runInContext(code, context);

const message = (id, time) => ({ messageId: id, senderId: 'u', senderName: '', isSelf: false,
  type: 'text', text: id, images: [], time });
const conversation = (cid, time) => ({ cid, rawCid: cid, otherUserId: cid, otherUserName: cid,
  otherUserAvatar: '', itemTitle: '', lastMessageSummary: cid, lastMessageTime: time, unreadCount: 0 });

(async () => {
  const pages = [
    { items: [message('m3', 3000), message('m2', 2000)], hasMore: true, nextCursor: 80 },
    { items: [message('m1', 1000)], hasMore: true, nextCursor: 60 },
  ];
  let calls = 0;
  const result = await context.recoverMessages(
    async (cursor) => pages[calls++],
    { cache: { msgs: [message('m1', 1000)], hasMore: true, cursor: 60 }, nextCursor: null },
    () => true,
  );
  assert.deepEqual(Array.from(result.items, (item) => item.messageId), ['m1', 'm2', 'm3']);
  assert.equal(result.complete, true);
  assert.equal(result.cursor, 60, '触及断线前边界后应保留原分页游标');

  let current = true;
  const stopped = await context.recoverMessages(
    async () => { current = false; return pages[0]; },
    { cache: { msgs: [message('old', 0)], hasMore: true, cursor: 1 }, nextCursor: null },
    () => current,
  );
  assert.equal(stopped, null, '请求代次失效后不得继续写入恢复结果');

  const many = await context.recoverMessages(
    async (cursor) => ({ items: [message(`m${cursor ?? 0}`, 1)], hasMore: true,
      nextCursor: (cursor ?? 100) - 1 }),
    { cache: { msgs: [message('never', 0)], hasMore: true, cursor: 0 }, nextCursor: null },
    () => true,
  );
  assert.equal(many.complete, false);
  assert.equal(many.items.length, 20, '恢复最多拉取 20 页');

  let convCalls = 0;
  const convResult = await context.recoverConversations(
    async () => ({ items: [conversation(convCalls ? 'old' : 'new', convCalls ? 90 : 100)],
      hasMore: true, nextCursor: convCalls++ ? 40 : 80 }),
    { cache: { convs: [conversation('old', 90)], hasMore: true, cursor: 80 }, nextCursor: null },
    () => true,
  );
  assert.equal(convResult.complete, true);
  assert.equal(convResult.cursor, 80, '会话恢复触及旧范围后保留原游标');
  assert.deepEqual(Array.from(convResult.items, (item) => item.cid), ['new']);
  console.log('PASS: chat history recovery freezes boundaries and stops stale pagination');
})().catch((error) => { console.error(error); process.exitCode = 1; });
