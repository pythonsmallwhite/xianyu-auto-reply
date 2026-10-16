# Web 批量发布交接

- 日期：2026-10-16；任务 task_2e36c64fbd1c / ctx_14d99c2d5473。
- 基线：`codex/web-batch-progress` / `f7c1e1ca18dff2b4e4747f72572df22c5d776123`，接手工作区干净。
- 审批：实际上下文 `approvals_reviewer=auto_review`；按本轮指定 gpt-6-astra / xhigh 执行，不使用子 agent。
- R25：Web 已实现待集成验证，默认 `address_mode=material`，缺素材 address 提前显示并阻断；显式 random 使用个人库、空库回退全局的说明。后端持久化/校验属于并行 worker。
- R26：Web 子项已离线验证，历史默认收起且不请求历史，点击后最近 5 次/默认首个；清晰表格包含账号、商品、状态、发布进度、预计时间、成功实际时间、错误和按需尝试；同步状态收进 details。
- 时间：pending 预计用 scheduled_at/available_at 较晚者；success 实际用 finished_at 或成功 attempt.finished_at，缺失显示未记录；非 success 不标已发布。
- R27：Web 已实现待集成验证，创建支持 0/1/3/5/12/24，无默认窗口，0 只允许一个账号，多选/清空清除非法选择；重试按任务允许保留原五档，严格只处理所选明确失败项。
- 并发保护：历史/详情独立请求序号、批次代次、后台轮询不抢占显式分页；旧响应/错误/loading 隔离；旧历史完成不清除当前发布记录，提供返回当前进度并防止绕过正在执行任务的提交保护。
- 保留：手工剩余额度、预留、unknown 平台人工核对、成功必须平台商品 ID、仅失败项重试；不改 Items/Orders/后端/mobile/全局样式。

## 验证

- `node tests/test_batch_publish_ui.cjs`：28 项通过，0 跳过；执行真实 TSX 组件、hooks/effects/事件和 API wrapper，所有服务响应均为离线替身，没有网络入口。
- 4 个内存变异均由对应断言发现：历史自动加载、计划时间冒充实际、取消多账号清理、取消批次代次隔离；不修改源码文件。
- `node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json`：通过。
- frontend `npm run build -- --outDir dist-batch-progress-check --emptyOutDir false`：通过，2541 modules，Vite 5.4.21；仅既有 autoRate 动静态导入警告。
- `git diff --check`：通过；原页面 BOM/CRLF 按既有文件保持，新增文件 UTF-8。
- 首次测试 harness 导出注入、跨 VM Error 构造器和未真正启动 deferred 请求的测试问题已修正，最终所有场景实际执行通过；没有把失败运行记为通过。

## 提交与接续

- 功能与交接 7 文件随本轮 commit，不 push；仅明确暂存本轮文件。
- 本树 frontend/node_modules 是指向 `D:/Myproject/xianyu-auto-reply/frontend/node_modules` 的 junction，只读复用；未安装/升级/修改共享依赖，构建产物不提交。
- 当前停点：worker 实现与离线验证完成，待协调器审查集成后端 address_mode 和 window_hours=0 冻结合同，再运行组合验证。
- 未做：真实浏览器视觉/平台请求/数据库迁移/部署；不能把离线组件测试当成浏览器或平台验收。
