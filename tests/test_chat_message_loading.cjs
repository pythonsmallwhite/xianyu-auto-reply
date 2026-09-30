const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../frontend/src/pages/chat-new/ChatNew.tsx'), 'utf8');
const tree = ts.createSourceFile('ChatNew.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
let expression;
let mergeExpression;
function walk(node) {
  if (ts.isVariableDeclaration(node)) {
    const name = node.name.getText(tree);
    if (name === 'loadMessages') expression = node.initializer.getText(tree);
    if (name === 'mergeMessages') mergeExpression = node.initializer.getText(tree);
  }
  ts.forEachChild(node, walk);
}
walk(tree);
assert.ok(expression);
assert.ok(mergeExpression, '未找到 mergeMessages');
const pending = [], writes = [], errors = [], loading = [];
const context = {
  useCallback: f => f, messageRequestRef: {current: 0},
  activeAccountIdRef: {current: 'a'}, activeCidRef: {current: 'one'}, msgCursor: null,
  getMessages: () => new Promise((resolve, reject) => pending.push({resolve, reject})),
  setMessages: value => writes.push(value), setMsgHasMore() {}, setMsgCursor() {},
  setLoadingMsgs: value => loading.push(value), addToast: value => errors.push(value),
};
vm.createContext(context);
const code = ts.transpileModule(
  `globalThis.mergeMessages = ${mergeExpression};\nglobalThis.load = ${expression};`,
  {compilerOptions: {target: ts.ScriptTarget.ES2020}},
).outputText;
vm.runInContext(code, context);
const apply = (prev, response) => {
  const update = writes.at(-1);
  return typeof update === 'function' ? update(prev) : update;
};
(async () => {
  const old = context.load('a', 'one');
  context.activeCidRef.current = 'two';
  const current = context.load('a', 'two');
  pending[0].resolve({messages: ['old'], hasMore: false, nextCursor: null});
  await old;
  assert.equal(writes.length, 0);
  assert.equal(loading.at(-1), true);
  pending[1].resolve({messages: ['current'], hasMore: false, nextCursor: null});
  await current;
  assert.equal(writes.length, 1);
  assert.equal(typeof writes[0], 'function');
  const staleError = context.load('a', 'two');
  context.activeAccountIdRef.current = 'b';
  pending[2].reject(new Error('stale'));
  await staleError;
  assert.equal(errors.length, 0);

  // 去重语义：推送与拉取携带相同 messageId 时不得重复渲染
  // 注意：merge 在 vm 上下文中创建数组，其原型与宿主 realm 不同，
  // deepStrictEqual 会比对原型而误判，故先展开成宿主数组再断言。
  const merge = (...args) => Array.from(context.mergeMessages(...args));
  const pushed = {messageId: 'm1', isSelf: false, type: 'text', text: 'hi', time: 1000};
  assert.deepEqual(merge([pushed], [{...pushed}], 'append'), [pushed], '同 id 消息必须去重');
  const localFailed = {messageId: '', isSelf: true, type: 'text', text: 'x', time: 2000, failed: true};
  assert.deepEqual(
    merge([localFailed], [{...localFailed}], 'append'),
    [localFailed],
    '无 id 的本地失败态在同文本同时刻下不得重复',
  );
  // 同文本但不同 messageId 必须各自保留（旧启发式会误删）
  const a1 = {messageId: 'a1', isSelf: true, type: 'text', text: 'ok', time: 3000};
  const a2 = {messageId: 'a2', isSelf: true, type: 'text', text: 'ok', time: 3100};
  assert.deepEqual(merge([a1], [a2], 'append'), [a1, a2], '不同 id 的同文本消息必须都保留');
  // 历史分页前置且去重
  const hist = {messageId: 'h1', isSelf: false, type: 'text', text: 'old', time: 500};
  const overlap = {messageId: 'm1', isSelf: false, type: 'text', text: 'hi', time: 1000};
  assert.deepEqual(
    merge([pushed], [hist, overlap], 'prepend'),
    [hist, pushed],
    '历史前置必须去重且保持顺序',
  );
  // replace 也必须去重，避免接口重复返回导致渲染 key 冲突
  assert.deepEqual(merge([], [pushed, {...pushed}], 'replace'), [pushed], '全量替换同样需要去重');
  assert.deepEqual(merge([pushed], [{...pushed}], 'replace'), [pushed], '快照重叠不能删除已有消息');
  const during = {...pushed, messageId: 'during', time: 2000};
  assert.deepEqual(merge([during], [pushed], 'replace'), [pushed, during], '快照请求期间推送必须保留且正序');
  console.log('PASS: stale success/error/loading do not overwrite another conversation');
})().catch(error => { console.error(error); process.exitCode = 1; });
