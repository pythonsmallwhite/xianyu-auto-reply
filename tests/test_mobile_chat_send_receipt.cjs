const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const assert = require('node:assert/strict');
const ts = require('../xianyu-mobile/node_modules/typescript');
const source = fs.readFileSync(path.join(__dirname, '../xianyu-mobile/api/wrappers/chat.ts'), 'utf8');
let reply, sent;
const ctx = {
  exports: {},
  require: () => ({getApiClient: async () => ({POST: async (url, options) => {sent = {url, options}; return reply;}}), extractError: async () => new Error('http failure')}),
  FormData: class { constructor() {this.fields = [];} append(...args) {this.fields.push(args);}},
};
vm.createContext(ctx);
vm.runInContext(ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2020}}).outputText, ctx);
(async () => {
  reply = {data:{success:true, data:{messageId:'platform-id', imageUrl:'https://cdn/test'}}};
  const result = await ctx.exports.sendImageMessage('a', 'c', 'u', 'file://test.jpg');
  assert.equal(result.messageId, 'platform-id');
  assert.deepEqual(Array.from(sent.options.body.fields, f=>f[0]), ['cid','toUserId','image']);
  assert.equal(sent.options.bodySerializer(sent.options.body), sent.options.body);
  reply = {data:{success:false, message:'rejected'}};
  await assert.rejects(ctx.exports.sendImageMessage('a','c','u','file://test.jpg'), /rejected/);
  reply = {error:{status:422}};
  await assert.rejects(ctx.exports.sendImageMessage('a','c','u','file://test.jpg'), /http failure/);
  reply = {data:{success:true, data:{messageId:'text-id'}}};
  assert.equal((await ctx.exports.sendMessage('a','c','u','offline')).data.messageId, 'text-id');
  const detail = fs.readFileSync(path.join(__dirname, '../xianyu-mobile/app/(tabs)/messages/[id].tsx'), 'utf8');
  const tree = ts.createSourceFile('detail.tsx', detail, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const helpers = []; let sync;
  function walk(n) {
    if (ts.isFunctionDeclaration(n) && ['isLocalMessage','isEchoOf','mergeMessages'].includes(n.name?.text)) helpers.push(n.getText(tree));
    if (ts.isVariableDeclaration(n) && n.name.getText(tree) === 'syncLatest') sync = n.initializer.getText(tree);
    ts.forEachChild(n, walk);
  }
  walk(tree);
  let resolve, state = [{messageId:'old', time:100}];
  const syncCtx = {useCallback:f=>f, account_id:'a', id:'c', console,
    getMessages:()=>new Promise(r=>{resolve=r;}), setMessages:f=>{state=Array.from(f(state));},
    cursorRef:{current:99}, hasMoreRef:{current:true}};
  vm.createContext(syncCtx);
  vm.runInContext(ts.transpileModule("const LOCAL_MSG_PREFIX='local-';const LOCAL_ECHO_WINDOW_MS=5000;" + helpers.join('\n') + '\nglobalThis.sync = ' + sync,
    {compilerOptions:{target:ts.ScriptTarget.ES2020}}).outputText, syncCtx);
  const pending = syncCtx.sync();
  state.push({messageId:'pushed', time:300});
  resolve({messages:[{messageId:'missed', time:200}], nextCursor:0, hasMore:false});
  await pending;
  assert.deepEqual(state.map(m=>m.messageId), ['old','missed','pushed']);
  assert.equal(syncCtx.cursorRef.current, 99);
  assert.equal(syncCtx.hasMoreRef.current, true);
  console.log('PASS: mobile upload/receipts/errors and actual reconnect callback ordering/cursor');
})().catch(e => {console.error(e); process.exitCode=1;});
