# Orca 主协调任务
用户于本轮明确授权接管开发：上一 AI 已停止收尾；允许临时任务分支和独立工作树并行开发，最终审查验证后合并到 main。你是持续协调者，负责拆解、派发、收集、集成，不要只给用户下一步提示词。所有模型必须 gpt-6.1-sol、xhigh，走用户独立中转站配置。最多 3 个开发 worker 加你 1 个协调者。

先完整阅读 AGENTS.md、PROJECT_STATE.md、docs/skills/project-handoff/SKILL.md，核对 git status、分支、HEAD 和源码。当前主目录 D:/Myproject/xianyu-auto-reply，最近 HEAD 1a9c4f9，本地 main 比 origin/main 领先 9 个提交；有大量上一 AI 已收尾但未提交源码、测试、文档。用户授权由你接管这些成果整理共同基线：审阅必要 diff 和验证证据，修复明确问题，按文件明确暂存并提交源码、测试及交接文档；不要 git add .，不要提交密钥、本地 .workbuddy 日志、outputs 补丁或构建产物，不覆盖/删除不属于你的文件。不要使用旧 origin/main 创建开发者工作树。先形成包含当前实现的完整本地 main 基线，再分派。

最新用户同意的协作规则覆盖历史“只在 main 开发”：开发者用 codex/ 前缀临时分支，独立工作树；你负责审查并合并 main。把此规则写入 AGENTS.md 与 PROJECT_STATE.md。开发者各自工作树维护交接，集成时由你保留完整需求并解决文档冲突。不要重复实施已完成的人工核对/HTTP/双端交互。现有历史测试记录不是你本轮验证结果。

运行 orca skills get orchestration 读取版本匹配指南，再按需要读取 coordinator-loop、placement-and-remote、low-level-topology 等指定 reference。使用真正 Orca orchestration run/task/dispatch/worker 和 inbox 生命周期调度，不用普通同目录 Codex subagents 代替独立工作树。项目 repo id 35886866-3cbf-4ec6-bfaf-66b674fc821b。新工作树必须基于你整理后的本地 main 或其明确 SHA。Orca 项目默认 setup 是根目录 npm install，需检查适用性；新工作树优先 --setup skip 后在正确子目录准备依赖，不盲跑根 npm install。

所有开发 worker 必须使用 C:/Users/zhishang_hu/.codex/.codex-orca/start-codex.cmd，传 --no-daemon --approve-for-me --model gpt-6.1-sol -c model_reasoning_effort=xhigh；用户于 2026-09-30 明确要求主协调和全部开发 worker 使用 Approve for me，通过生效上下文 approvals_reviewer=auto_review 验证。自动审批内部审查进程不计入开发 worker 并发数。不要退出桌面 Codex 账号，不改默认 .codex/config.toml/auth.json，不输出独立配置中的密钥。验证 Orca configured launcher 实际使用该命令；worker-start 不能表达时先读 low-level-topology 再用文档规定的自定义命令流程。新终端需等待 tui-idle 后投递；超时先检查残留，不重复创建。历史首次 terminal create 曾超时，未得到新 handle；不要盲目清理任何残留。

先核实后设计第一轮独立任务，建议方向仅作技术候选：
A 隔离 MySQL 迁移、双 worker 竞争/恢复验收及必要修复；
B Ubuntu 单机当前定制源码一键部署、升级、备份恢复与健康检查；
C 根据实际源码选择客户端上线缺口或一个可核验的平台商品动作。
每项必须定义文件所有权、禁止改动范围、输入输出接口、可观察验收。不让多个 worker 同改数据库/共享接口。API 尚未确定则先冻结合同再并行前后端。未取得视频协议继续记阻塞，不猜协议；恢复不以重新发布替代。MySQL 只能用隔离实例/限定测试库，不读取生产连接做实验。安装服务/重型环境前评估现有资源，不覆盖生产数据。

完成第一轮后审查 diff、执行适当验证、合并本地 main，更新交接与任务状态，可继续下一批已确认一期需求，直到功能完成或出现必须用户提供的信息。避免无依据扩需求或重复全套测试。真实平台、浏览器/真机、离线测试状态分别报告；无真实平台授权不发送消息/操作商品订单。不自动 push、不部署到服务器，最终列明待推送和待上线验证。遇需人工批准时明确在 Orca 告知用户。
