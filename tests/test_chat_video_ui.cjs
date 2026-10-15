const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../frontend/node_modules/typescript');

const apiSource = fs.readFileSync(path.join(__dirname, '../frontend/src/api/chatNew.ts'), 'utf8');
let request;
const api = {
  exports: {}, URL,
  FormData: class { constructor() { this.fields = []; } append(...args) { this.fields.push(args); } },
  require: () => ({ post: async (...args) => { request = args; return { success: true }; } }),
};
vm.createContext(api);
vm.runInContext(ts.transpileModule(apiSource, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText, api);

const source = fs.readFileSync(path.join(__dirname, '../frontend/src/pages/chat-new/ChatNew.tsx'), 'utf8');
const tree = ts.createSourceFile('ChatNew.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const expressions = {};
function walk(node) {
  if (ts.isVariableDeclaration(node) && ['sendVideoFile', 'handleVideoSelected', 'clearPendingVideo'].includes(node.name.getText(tree))) {
    expressions[node.name.getText(tree)] = node.initializer.getText(tree);
  }
  ts.forEachChild(node, walk);
}
walk(tree);

const pending = [], applied = [], toasts = [], revoked = [];
let selected = null, nextUrl = 0;
const ctx = {
  useCallback: fn => fn, activeAccountId: 'a', activeCid: 'c', sending: false,
  conversations: [{cid: 'c', otherUserId: 'buyer'}], videoSendingRef: {current: false},
  pendingVideoRef: {current: null}, videoPreviewUrlsRef: {current: new Set()},
  URL: {createObjectURL: () => `blob:video-${++nextUrl}`, revokeObjectURL: url => revoked.push(url)},
  setPendingVideo: value => { selected = value; }, setSending: value => { ctx.sending = value; },
  addToast: toast => toasts.push(toast), applySentMessage: (...args) => applied.push(args),
  sendVideoMessage: (...args) => new Promise((resolve, reject) => pending.push({args, resolve, reject})),
};
vm.createContext(ctx);
for (const name of ['clearPendingVideo', 'handleVideoSelected', 'sendVideoFile']) {
  assert.ok(expressions[name], `missing ${name}`);
  vm.runInContext(ts.transpileModule(`globalThis.${name} = ${expressions[name]}`, {compilerOptions: {target: ts.ScriptTarget.ES2020}}).outputText, ctx);
}

(async () => {
  const file = {name: 'test.mp4', type: 'video/mp4', size: 100};
  await api.exports.sendVideoMessage('a', 'c', 'buyer', file);
  assert.equal(request[0], '/api/v1/chat-new/send-video/a');
  assert.deepEqual(Array.from(request[1].fields, entry => entry[0]), ['cid', 'toUserId', 'video']);
  assert.equal(request[2].timeout, 240000);
  assert.equal(api.exports.proxyCdnVideoUrl('https://gw.alicdn.com/v.mp4'), '/api/v1/chat-new/image-proxy?url=https%3A%2F%2Fgw.alicdn.com%2Fv.mp4');
  assert.equal(api.exports.proxyCdnVideoUrl('https://down.im.dingtalk.cn/v.mp4'), '/api/v1/chat-new/video-proxy?url=https%3A%2F%2Fdown.im.dingtalk.cn%2Fv.mp4');
  assert.equal(api.exports.proxyCdnVideoUrl('blob:preview'), 'blob:preview');

  const event = {target: {files: [file], value: 'test'}};
  ctx.handleVideoSelected(event);
  assert.equal(event.target.value, '');
  assert.equal(selected.file, file);
  assert.equal(pending.length, 0, 'selection only previews; must not send');
  const preview = selected.previewUrl;
  const sending = ctx.sendVideoFile(file);
  assert.ok(revoked.includes(preview), 'pending preview released after send starts');
  await ctx.sendVideoFile(file);
  assert.equal(pending.length, 1, 'double click must not submit twice');
  ctx.activeAccountId = 'other'; ctx.activeCid = 'other-chat';
  pending[0].resolve({success: true, data: {messageId: 'server', videoUrl: 'https://gw.alicdn.com/v.mp4'}});
  await sending;
  assert.equal(applied[0][0], 'a'); assert.equal(applied[0][1], 'c');
  assert.equal(applied[0][2].messageId, 'server');
  assert.equal(applied[0][3], '[视频]');
  assert.equal(ctx.videoPreviewUrlsRef.current.size, 0, 'successful upload releases local video');

  ctx.activeAccountId = 'a'; ctx.activeCid = 'c';
  const failed = ctx.sendVideoFile(file);
  pending[1].resolve({success: false, message: 'rejected'});
  await failed;
  assert.equal(applied[1][2].failed, true);
  assert.equal(applied[1][2].failReason, 'rejected');
  assert.equal(applied[1][3], null, 'failure must not update conversation summary');
  assert.equal(ctx.videoPreviewUrlsRef.current.size, 1, 'failed video remains playable locally');

  const missingReceipt = ctx.sendVideoFile(file);
  pending[2].resolve({success: true, data: {videoUrl: 'https://gw.alicdn.com/v.mp4'}});
  await missingReceipt;
  assert.equal(applied[2][2].failed, true, 'missing receipt must not be shown as successful');
  for (const invalid of [{...file, type: 'text/plain'}, {...file, size: 0}, {...file, size: 21 * 1024 * 1024}]) {
    ctx.handleVideoSelected({target: {files: [invalid], value: ''}});
    assert.equal(selected, null);
  }
  console.log('PASS: video multipart/proxy/preview/receipt/failure/double-send/account-scoping');
})().catch(error => { console.error(error); process.exitCode = 1; });
