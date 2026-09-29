/**
 * Android 批次记录：清除与异步写入竞态的离线回归。
 *
 * 直接抽取 `xianyu-mobile/app/(tabs)/mine/product-publish.tsx` 中的
 * `persistRecord` / `clearRecord` 函数体，在受控的 AsyncStorage 替身上运行，
 * 验证“清除中/已清除”不会被子在途写入重新落盘或复活到内存状态。
 * 仅验证存储与状态隔离，不代表真机或 Expo 构建验收。
 *
 * 场景性质（已用补丁前版本逐条反向验证）：
 *   1 清除期间的新写入被拒绝      —— 补丁前失败，属于竞态回归
 *   2 在途写入晚于清除完成        —— 补丁前失败，属于竞态回归（核心场景）
 *   3 清除后写入仍可用            —— 补丁前后均通过，防止保护被写成永久禁用
 *   4 并发写入串行化              —— 补丁前后均通过，保证排队语义未退化
 *   5 清除被拒绝时无副作用        —— 补丁前失败，覆盖重复清除/进行中拦截
 *
 * 可用 RACE_ONLY=2 等环境变量单独运行某条场景，便于补丁前后对照。
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../xianyu-mobile/node_modules/typescript');

const SOURCE_RELATIVE = '../xianyu-mobile/app/(tabs)/mine/product-publish.tsx';
const STORAGE_KEY = 'publish_batch:test:1';
const CLEAR_BUTTON_TEXT = '已核实，清除';

const sourcePath = path.join(__dirname, SOURCE_RELATIVE);
const source = fs.readFileSync(sourcePath, 'utf8');
const tree = ts.createSourceFile('product-publish.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

const captured = {};
function walk(node) {
  if (ts.isVariableDeclaration(node)) {
    const name = node.name.getText(tree);
    if ((name === 'persistRecord' || name === 'clearRecord') && node.initializer) {
      captured[name] = node.initializer.getText(tree);
    }
  }
  ts.forEachChild(node, walk);
}
walk(tree);
assert.ok(captured.persistRecord, '未在 product-publish.tsx 中找到 persistRecord');
assert.ok(captured.clearRecord, '未在 product-publish.tsx 中找到 clearRecord');

/** 构造一个可精确控制 AsyncStorage 时序的受控环境 */
function createHarness({ record = { kind: 'finished', batchId: 'b1' } } = {}) {
  const stored = new Map();
  const writes = [];          // 每次 setItem 成功落盘的载荷（按完成顺序）
  const removes = [];         // 每次 removeItem 的 key
  const stateWrites = [];     // 每次 setRecord 的入参
  const alerts = [];
  const pending = [];         // 被挂起的 setItem 放行器
  let holdSetItem = false;

  const AsyncStorage = {
    setItem(key, value) {
      const commit = () => {
        stored.set(key, value);
        writes.push(value);
      };
      if (!holdSetItem) {
        commit();
        return Promise.resolve();
      }
      return new Promise((resolve) => {
        pending.push(() => {
          commit();
          resolve();
        });
      });
    },
    removeItem(key) {
      stored.delete(key);
      removes.push(key);
      return Promise.resolve();
    },
  };

  const noop = () => {};
  const context = {
    useCallback: (fn) => fn,
    storageKey: STORAGE_KEY,
    record,
    AsyncStorage,
    Alert: { alert: (title, message, buttons) => alerts.push({ title, message, buttons }) },
    setRecord: (value) => stateWrites.push(value),
    clearGenerationRef: { current: 0 },
    clearingRef: { current: false },
    storageOperationRef: { current: Promise.resolve() },
    setClearing: noop,
    statusGenerationRef: { current: 0 },
    detailGenerationRef: { current: 0 },
    checkingRef: { current: false },
    detailLoadingRef: { current: false },
    targetPageRef: { current: 1 },
    targetStatusRef: { current: new Map() },
    setChecking: noop,
    setDetailLoading: noop,
    setTargets: noop,
    setTargetPage: noop,
    setTargetTotal: noop,
    setSelectedRetryTargetIds: noop,
    setRetryWindowHours: noop,
    setProgress: noop,
    setStatusError: noop,
    console,
  };
  vm.createContext(context);
  const code = ts.transpileModule(
    `globalThis.persistRecord = ${captured.persistRecord};\nglobalThis.clearRecord = ${captured.clearRecord};`,
    { compilerOptions: { target: ts.ScriptTarget.ES2020 } },
  ).outputText;
  vm.runInContext(code, context);

  return {
    context,
    stored,
    writes,
    removes,
    stateWrites,
    alerts,
    /** 让后续 setItem 挂起，模拟慢速磁盘写入 */
    hold: () => { holdSetItem = true; },
    /** 放行所有挂起写入；之后的新写入立即完成 */
    release: () => {
      holdSetItem = false;
      const waiting = pending.splice(0, pending.length);
      for (const run of waiting) run();
    },
    flush: () => new Promise((resolve) => setImmediate(resolve)),
    /** 触发“已核实，清除”按钮并返回确认框 */
    pressClear: () => {
      context.clearRecord();
      const dialog = alerts.at(-1);
      assert.ok(dialog, 'clearRecord 未弹出确认框（record 可能仍为进行中）');
      const button = dialog.buttons.find((item) => item.text === CLEAR_BUTTON_TEXT);
      assert.ok(button, `确认框中缺少「${CLEAR_BUTTON_TEXT}」按钮`);
      button.onPress();
      return dialog;
    },
  };
}

(async () => {
  // 场景可按需单独运行，便于对补丁前后做逐条对照（默认全跑）
  const only = process.env.RACE_ONLY
    ? new Set(process.env.RACE_ONLY.split(',').map((item) => Number(item.trim())))
    : null;
  const enabled = (index) => !only || only.has(index);

  // 1. 清除刚开始时发起的写入必须被拒绝，且不落盘、不污染内存状态
  if (enabled(1)) {
    const h = createHarness();
    h.pressClear();
    // 同一次微任务内发起写入：此时 clearRecord 已同步置位 clearingRef
    const duringClear = assert.rejects(
      () => h.context.persistRecord({ kind: 'uncertain', batchId: 'b2' }),
      /清除/,
      '清除中的写入必须显式失败而不是静默丢弃',
    );
    await duringClear;
    await h.flush();
    assert.deepEqual(h.writes, [], '被拒绝的写入不得落盘');
    assert.deepEqual(h.removes, [STORAGE_KEY], '清除必须删除存储项');
    assert.equal(h.stored.has(STORAGE_KEY), false, '清除后存储中不得残留记录');
    assert.equal(h.stateWrites.at(-1), null, '内存状态最终必须为已清除');
  }

  // 2. 清除前已发起的在途写入晚于清除完成时，不得复活存储与内存状态
  if (enabled(2)) {
    const h = createHarness();
    h.hold();
    const inflight = h.context.persistRecord({ kind: 'uncertain', batchId: 'b1' });
    inflight.catch(() => {});
    await h.flush();                     // 让在途写入真正进入被挂起的 setItem
    h.pressClear();                      // 清除必须排队等待该写入
    assert.deepEqual(h.removes, [], '清除不得抢在在途写入之前删除存储');
    h.release();
    await inflight.then(
      () => assert.fail('在途写入跨越清除后必须失败'),
      (error) => assert.match(error.message, /清除/),
    );
    await h.flush();
    assert.equal(h.stored.has(STORAGE_KEY), false, '在途写入不得在清除后留在存储中');
    assert.equal(h.stateWrites.at(-1), null, '内存状态最终必须为已清除');
    assert.ok(
      !h.stateWrites.some((item) => item && item.batchId),
      '清除后不得再写入任何批次记录',
    );
  }

  // 3. 清除完成后（clearingRef 已复位）普通写入仍必须正常工作，避免保护被写成永久禁用
  if (enabled(3)) {
    const h = createHarness();
    h.pressClear();
    await h.flush();
    assert.equal(h.context.clearingRef.current, false, '清除流程结束后必须复位 clearingRef');
    const next = { kind: 'active', batchId: 'b3' };
    await h.context.persistRecord(next);
    assert.deepEqual(h.writes, [JSON.stringify(next)], '清除完成后新批次必须能正常落盘');
    assert.deepEqual(h.stateWrites.at(-1), next, '清除完成后新批次必须能正常写入内存状态');
    assert.equal(h.stored.get(STORAGE_KEY), JSON.stringify(next));
  }

  // 4. 串行化：并发写入按调用顺序落盘，不发生交错覆盖
  if (enabled(4)) {
    const h = createHarness();
    const first = { kind: 'active', batchId: 'a' };
    const second = { kind: 'active', batchId: 'b' };
    h.hold();
    const p1 = h.context.persistRecord(first);
    const p2 = h.context.persistRecord(second);
    await h.flush();                     // 首个写入已被挂起，第二个仍在排队
    assert.deepEqual(h.writes, [], '挂起期间不得有任何落盘');
    h.release();
    await Promise.all([p1, p2]);
    assert.deepEqual(h.writes, [JSON.stringify(first), JSON.stringify(second)], '并发写入必须按序落盘');
    assert.deepEqual(h.stateWrites, [first, second], '并发写入的状态更新必须按序');
  }

  // 5. 清除被拒绝时不得产生任何副作用（进行中的批次 / 已在清除 / 无 storageKey）
  if (enabled(5)) {
    const active = createHarness({ record: { kind: 'active', batchId: 'b1' } });
    active.context.clearRecord();
    assert.deepEqual(active.alerts, [], '进行中的批次不得弹出清除确认');
    assert.deepEqual(active.removes, [], '进行中的批次不得删除存储');
    assert.equal(active.context.clearingRef.current, false, '被拒绝的清除不得置位 clearingRef');

    const inProgress = createHarness();
    inProgress.context.clearingRef.current = true;
    inProgress.context.clearRecord();
    assert.deepEqual(inProgress.alerts, [], '已在清除中不得重复弹出确认');

    const noKey = createHarness();
    noKey.context.storageKey = '';
    noKey.context.clearRecord();
    assert.deepEqual(noKey.alerts, [], '登录未就绪时不得弹出确认');
  }

  console.log('PASS: android batch storage clear/persist race is isolated');
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
