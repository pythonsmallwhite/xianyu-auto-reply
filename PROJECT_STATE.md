# 项目需求与 AI 交接文档

更新时间：2026-09-30（Asia/Shanghai；main / 8a60b7f；主协调新一轮及三个 worker 已生效 auto_review，原 Run 继续；原会话只读）

> 发给下一位 AI 的统一入口，每轮开发结束必须更新。已收录需求确认稿 v0.5 全文及后续口径；原文中的建议和待定项不等于用户已确认需求。

## 1. 给接手 AI 的指令

完整阅读本文及根目录 AGENTS.md，核对实际分支、HEAD、工作区及相关源码，说明当前停点后按用户本轮要求继续。结束前更新本文。不要仅凭 commit 标题或历史测试结果宣称完成。

如果只有本文而没有仓库权限，先取得代码或仓库位置。Markdown 可以传递上下文，但不包含源码、环境和未提交文件内容。

## 2. 背景与基线

- 项目：闲鱼多账号自动回复及自动化系统，在已有仓库上继续开发。
- 工作目录：D:\Myproject\xianyu-auto-reply。
- 用户经常切换 AI，需要需求、状态、验证及下一步持续保存在文档中。
- 2026-09-29 开发轮继续完成持久批量发布；独立审查固定 0f20e1d 的发现保留在交接历史，两轮验证范围分开记录。
- 当前分支 main，检查时 HEAD 为 `8a60b7f`，领先 origin/main 11 个提交；共同基线为 `e2e29537b788e16f457e06d084720fa901e68d95`，8a60b7f 保存 Orca 派发检查点。30 个明确源码/测试/协作文档及重复下架路由修正已包含；没有 push。三个本地产物目录未暂存，全部保留。
- 原开发基线为 1be6493c36f8c66547b91d3940ac32580b1937b9。旧交接记载用户要求直接在 main 开发；本轮明确授权改为 `codex/` 临时分支、独立工作树并行，主协调审查后集成 main。
- 已从用户指定会话“阅读两个上下文”找回 v0.5 原文件，全文嵌入文末。来源：codex://threads/01a0e5e4-1873-7c10-aaa4-94567e3174d1。
- 历史授权仅作为上下文，不自动扩大本轮操作范围。

## 3. 需求与验收台账

需求来源见文末 v0.5 全文及下方“后续口径”。旧交接仅作为历史证据；原稿的建议、待设计项与用户确认需求严格区分。执行器、预留账本等为实现方案，不因代码已存在就变成用户确认的业务规则。

| ID | 需求与约束 | 来源 | 当前状态与证据 | 验收缺口 |
| --- | --- | --- | --- | --- |
| R01 | 多商品、多批次排程，最小间隔按每个内部商品计算，五档窗口 | v0.5 / 后续交接 | 已实现待验证；五档窗口已持久化到批次/目标/尝试，按内部商品生成计划，并由商品级协调记录校验实际请求发起间隔；测试 37 项相关回归通过 | MySQL 迁移、多进程 worker、真实时间精度和真实平台仍待验证 |
| R02 | 内部商品、平台 ID 映射、来源类别、剩余额度、库存账本 | v0.5 / 后续交接 | 进行中；基础实现已提交，CR01/CR02 已修复并通过离线回归；本轮发布执行保留容量预留和未知结果保护 | 真实 MySQL 迁移及平台库存动作尚未验证 |
| R03 | 持久批次、逐项目标、尝试记录、重启恢复，接入四类批量操作 | v0.5 / 后续交接 | 进行中；发布与关联商品下架已有持久执行器；下架具备人工核对、真实目标路由 HTTP 及双端交互离线回归 | MySQL 升级/多 worker、真实下架验收、修改和擦亮待完成 |
| R04 | 发布、下架、恢复、编辑含图片、擦亮；保护历史商品、逐项状态、仅失败项重试 | v0.5 / 后续交接 | 进行中；关联商品下架及 unknown 人工核对已离线验证，成功/未知禁重发、失败新窗口和状态版本保护已有回归 | 恢复接口证据、编辑含图片、擦亮和平台验收未完成；不把离线下架等同全部商品动作 |
| R05 | 订单事件驱动共享库存联动 | v0.5 / 后续交接 | 进行中；订单服务和库存服务有提交 | 可用库存耗尽触发延迟下架，取消后 > 0 恢复因库存下架的关联商品；平台闭环待验证 |
| R06 | 统一聊天和实体物流发货，不用提醒或卡券发送代替 | v0.5 / 后续交接 | 进行中；聊天账号归属保护已提交，物流完成情况未核实 | 查看收货地址、填写快递单号并提交；失败提示后可暂缓修复，结果未知不自动重复提交；平台必填字段待核验 |
| R07 | Web 与指定 Android 操作界面 | v0.5 / 后续交接 | 进行中；两端发布界面有提交；下架/人工核对/显式刷新已实现，真实组件函数/effect 离线交互 68 场景通过 | 浏览器/真机、APK、恢复/编辑含图片、买家资料及物流仍待完成；持续任务在后端 |
| R08 | AI 文案、通知、安全、离线和真实场景验收 | v0.5 / 后续交接 | 进行中；安全有部分提交，其他定制范围待确认 | AI 开关调用用户接口微调表达；任务日志、失败原因、通知和失败项手动重试；不新增 AI 自动回复/议价需求 |
| R09 | 跨 AI 保留完整需求及最新进度，每轮更新文档 | 本轮用户要求 | 已实现待验证；本文和 AGENTS.md 已建立 | 原始需求已补齐；下轮开发仍需实际执行维护规则 |
| R10 | 买家基本信息、主页公开动态、在售商品、评价 | v0.5 第八节 | 已有功能是否覆盖未核实 | 不可获取可留白或提示暂不可用，不阻塞其他流程 |
| R11 | 历史商品隔离、人工下架范围与确认弹窗 | v0.5 第三节 | 进行中；来源分类和相关 Web 改动已提交 | 默认隐藏；历史商品仅当前账号单件下架；关联商品可选全部或部分账号，确认前不创建任务 |
| R12 | 聊天发送视频消息 | 本轮用户明确要求 / issue #297 | 阻塞；现有 xianyu_publish_video 仅为商品素材上传，IM/聊天 API 没有视频发送；用户确认“暂无，先完成其他功能并记录视频协议缺口” | 取得脱敏协议与限定验收范围后实现上传、发送、回执、历史/推送解析及两端展示；不猜协议或假成功 |
| R13 | 评估并修复聊天实时同步及移动可用性 | 用户要求评估 #304/#339；一期优先级为本轮技术建议 | 进行中；广播集合并发、历史错误伪空列表、切会话旧请求覆盖已修复并离线验证；本轮完成重连补拉（区分首连/重连）、稳定 `messageId` 去重合并、会话列表分页保留、非当前会话缓存更新、迟到发送结果按账号/会话隔离；Android 聊天详情与列表同步实现消息合并、重连补拉、账号标识、贴底滚动与分页入口修正，21 项离线场景通过并逐条变异证伪 | 浏览器/真机内真实重连与后台恢复交错验证、后台恢复缓存刷新穷尽验证、移动窄屏其余页面与 Release APK 真机验收仍未完成 |
| R14 | Ubuntu 单台云服务器、一键部署 | 用户直接指定 / 本轮协调任务 | 进行中；Orca worker B 在独立工作树开发当前源码部署、升级和备份恢复脚本，合同沿用 docs/NEXT_AI_PROMPT.md | 脚本须保留配置/数据、健康检查、迁移备份与恢复；干净 Ubuntu 首装/升级/重启实测仍待完成 |
| R15 | 评估风控时间/筛选与浏览器替换 | 用户指定 #99/#302 | 已完成代码层评估；#99 一期回归/必要局部修复，#302 二期试验为技术建议 | #99 现有筛选经查询提交，数据库时区和无时区序列化待实测；#302 不按“完美迁移”假设整体替换 |


状态统一使用：未开始 / 进行中 / 已实现待验证 / 已验证 / 阻塞。当前为保守交接核对，不是完整产品审计。

### 本轮已确认口径

- **最新用户要求（2026-09-30，本轮）：作为 Orca 主协调接管并执行 docs/ORCA_COORDINATOR_TASK.md。** 此授权取代历史暂停；先审查、验证并按文件提交既有源码/测试/交接形成共同基线，再用 Orca Run/Task/Dispatch 在独立工作树并行开发，最终审查集成 main。最多三个 worker，全部使用指定启动脚本及 `gpt-6.1-sol` / `xhigh`；不自动 push 或部署，不操作真实账号/商品/订单/消息。此前 lease 复位、移动存储竞态及人工核对/HTTP/双端交互不重复实施。
- 视频聊天当前缺协议证据，用户明确同意先完成其他功能并记录缺口。没有发送真实消息，也没有伪造视频发送接口。
- 详尽的 Issue 评估、下一轮开发提示词及 Ubuntu 自动部署交付要求见 docs/NEXT_AI_PROMPT.md；核心新需求与状态已在 R12—R15 记录。
- 本轮按 NEXT_AI_PROMPT 要求优先完成一期聊天可靠性：重连补拉、稳定 ID 去重合并、恢复后缓存刷新边界、非当前会话缓存更新、迟到响应按账号/会话隔离；移动窄屏可用性尚未处理。

- 用户确认失败项重试采用“新开窗口”：重试请求必须重新选择 1、3、5、12、24 小时，只作用于明确失败项；成功、未知、跳过项不可重试。
- 五档窗口创建和重试均不预选默认值，Web 与 Android 都必须显式选择窗口。
- 用户本轮直接要求所有开发智能体（含主协调）启用 Approve for me，稳定协调项 `OC03`。新 worker 在原指定脚本/模型参数基础上追加 --approve-for-me；验收为实际上下文 approvals_reviewer=auto_review，保留 workspace-write 和既有授权边界。此口径覆盖此前本轮暂不改变审批设置的阶段表述，不修改全局配置或默认账号。

### 来源与后续口径

完整原文见文末“附录 B”，保留其已确认、建议、待定的区分。原文件日期为 2026-09-20；源路径为 C:/Users/zhishang_hu/WorkBuddy/2026-09-15-16-32-28/outputs/xianyu-requirements-v0.5.md。

后续来源：用户指定会话“阅读两个上下文”（01a0e5e4-1873-7c10-aaa4-94567e3174d1），及该会话引用的 xianyu-session-handoff-2026-09-28.md。记录层级如下：

- 会话中可直接读取的用户原话：“可以直接在main上开发，这个项目只有我自己一个人做”。后续直接在 main 开发，不重复要求创建分支。
- 会话中可直接读取的用户选择：“先完成离线开发，稍后提供测试对象（推荐）”。真实账号、商品、消息及发货验收仍等待限定对象与授权。
- 会话中可直接读取的用户要求：“继续完成其他功能开发”及后续“继续”。因此旧文档“只做审计、不修改业务代码、阶段 0 停止”的阶段性限制已被后续开发要求取代；当前开发轮继续业务实现，独立审查轮只核对固定提交。
- 后续接力文档记载：采用当前开源底座及其 Expo/React Native Android 工程，本地打包 Release APK，持续任务由后端执行。v0.5 的“框架和移动端形态未选定”属于历史状态。
- 已有 PROJECT_STATE.md 记载多商品、多批次最小间隔按每个内部商品分别计算；本次会话读取未返回对应原始问答，保留为后续交接口径，不伪装成直接原话。不要退回“尚未选择按商品/整批/全局”的旧状态。
- 个人自用，通常不超过 10 账号，不设为硬上限；不扩展为复杂多用户商业平台或插件系统。

### 核心验收清单

1. 手工剩余额度：平台总容量 200、历史 50，用户填 150 就是剩余 150，不再减去 50；不足项跳过，其他项继续，不自动下架历史商品腾额度。
2. 历史商品默认隐藏，可主动显示；只对当前账号单件下架且弹窗确认，无跨账号批量选项。来源不明不按标题猜测归组，不纳入新批次或库存联动。
3. 工具关联商品可选择全部关联账号或指定账号下架；确认弹窗展示商品、目标账号、数量和执行方式，取消不创建任务。自动库存联动不因此改为每次人工审核。
4. 库存 3、发布 5 账号，每单 1 件：第 3 单占用后，其余 2 个商品延迟下架；取消 1 单后可用库存为 1，仅这 2 个因库存不足自动下架的商品延迟恢复。总库存仍为 3，不恢复人工下架或历史商品。
5. 上架、下架、修改、擦亮支持 1/3/5/12/24 小时随机分散；同商品 N 账号相邻间隔至少 T/(2N)。5 账号 1 小时至少 6 分钟；异常超时不能伪装完成或静默顺延。
6. 批量修改明确含图片，不误修改历史商品。AI 文案可关闭，使用用户自己的接口，只改表达，不编造商品事实；不是新增 AI 自动回复或自动议价。
7. 任务详情定位到账号和商品，状态、失败原因、日志、通知可查；单项失败继续其余项，手动重试仅失败项，成功项不重复，未知结果先核对。
8. 集中聊天显示卖家账号并可回复；买家资料不可获取可留白或提示暂不可用，不阻塞流程。
9. 查看订单地址、填写实体快递单号并在闲鱼发货流程提交；展示真实结果，失败可先提示并暂缓修复，不要求复杂自动补偿。卡券或无物流发货不代替实体快递。
10. Android 支持批量上下架、修改含图片、回复、买家信息、地址、快递单号；构建 Release APK。移动端擦亮、完整任务中心和日志未被确认为必选范围。

### 真正仍待设计的细节（不阻塞全部离线开发）

- 手工额度成功扣减、并发预留、下架是否释放、平台外操作如何校准：现有预留实现是技术方案，不等于已确认业务规则，不假设下架必然返还额度。
- 图片替换/追加/删除/排序的具体组合；标题、描述、价格、运费等编辑字段。
- AI 接口协议、调用失败和重复文案的处理，不默认失败后用原文继续发布。
- 多件订单、自动关闭、已发货退款、退货入库规则；退款完成不等于实物可售。
- 通知渠道、多选失败项重试、暂停/取消控制；手机端擦亮、完整任务中心和日志范围。
- 平台要求的快递公司等必填字段及真实能力核验。可延后容量自动读取、历史数据获取能力、买家公开信息获取能力和发货复杂异常修复。

## 4. 项目结构与实现入口

技术栈（据 README）：FastAPI、SQLAlchemy、MySQL、Redis、Playwright；Web 为 React + TypeScript + Vite；Android 客户端在 xianyu-mobile。

| 路径 | 职责或继续入口 |
| --- | --- |
| backend-web/app/api/routes/product_publish.py | 发布接口 |
| backend-web/_bootstrap.py | 应用生命周期和执行器接线入口 |
| common/db/init_database.py | 数据库初始化、字段补齐 |
| common/models/internal_product.py | 内部商品、平台映射、订单库存占用 |
| common/services/internal_product_service.py | 映射、订单事件、库存和动作校验 |
| common/services/publish_capacity_service.py | 发布额度预留、结算、未知结果处理 |
| common/utils/batch_schedule.py | 排程纯规则 |
| websocket/、scheduler/ | 消息连接、定时任务 |
| frontend/src/pages/product-publish/ | Web 发布界面 |
| xianyu-mobile/app/(tabs)/mine/product-publish.tsx | Android 发布界面 |
| promotion/ | 返佣子系统，独立前后端 |
| tests/ | 排程、聊天归属、商品、库存、来源、额度、结果测试 |

安装启动参考 README；示例配置不代表当前环境实况。不在本文保存凭据、Cookie 或买家隐私。

## 5. 当前停点与未提交工作

### 最新：新 Orca 会话继续接管（2026-09-30，本轮进行中）

- 来源：用户继续指令及 `docs/ORCA_COORDINATOR_TASK.md`。`OC01` 已验证并提交为 e2e2953；`OC02` 进行中，三个真实 Orca 独立工作树已派发，后续审查与 main 集成待完成。
- `OC03` 已验证：三个开发 worker 的实际会话上下文均为 on-request / auto_review，模型 gpt-6.1-sol；主协调上一运行轮仍为 reviewer=user，权限菜单虽显示 Approve for me (current)，用户中断后新一轮的生效执行配置已为 auto_review，且已出现 cwd 为主目录的自动审查内部进程。保持原 Run/Task/Dispatch 和工作树，无新建重复 worker，不再循环操控权限菜单。
- Orca 1.4.215，Run `run_f7192cc83c24`，coordinator `term_b4a2a113-8e22-4243-a113-8768bbc67a07`。三个 worker 都基于共同基线完整 SHA，setup skip；实际分支均修正为 codex/ 前缀。使用指定 start-codex.cmd --no-daemon --model gpt-6.1-sol -c model_reasoning_effort=xhigh；终端实际显示 GPT-6.1-Sol xhigh，tui-idle 后派发，三个已输出 Working 和文件读取。自定义终端的 fleet 状态因 missing_status 为 unverifiable，不能仅凭 PTY 在线宣布任务完成。
- 上一会话基线验证（历史证据）：Python 全套 141/141，0 失败/0 跳过，112.831 秒；六组 Node、双端类型检查通过。本会话提交前专项：`-B -m unittest tests.test_listing_actions tests.test_offline_api_http -q` 52/52，0 失败/0 跳过，34.950 秒；下架 UI 68/68、移动聊天回执/图片上传/补拉回调、Android 完整 `tsc --noEmit` 和暂存 diff 检查通过。MySQL、浏览器/真机、APK、平台、Ubuntu 尚未验证。
- 基线及派发交接均已提交；主目录本轮只更新 AGENTS.md、协调任务启动参数和本文。三个产物目录保持未跟踪。Windows 沙箱 1385 和 apply_patch reparse 误报通过正常用户环境处理；用户批准的是会话 auto_review，不修改全局配置或默认账号。Git 另有历史 .orca-preparing 锁定残留，基于旧 origin/main，本轮不触碰。
- Worker A：task_64593bab2be4 / ctx_ce4084de84fb，codex/mysql-acceptance-0930，文件范围为数据库初始化、指定 worker/model、tests/test_mysql*、scripts/mysql*、docs/orca/mysql-acceptance.md。目标为隔离 MySQL 迁移、精度、锁竞争/恢复及必要修复；无隔离实例则交付验收 harness 并如实记录环境阻塞。
- Worker B：task_35ba85f0c3cc / ctx_2604c8b0648b，codex/ubuntu-deploy-0930，scripts/deploy-ubuntu.sh、docker/ubuntu*、部署文档/测试；业务源码和数据库只读，既有 Compose 不改。目标为源码部署、升级、备份恢复及离线验证，未授权上线部署。
- Worker C：task_5a1ca361abd3 / ctx_08415b6833c1，codex/chat-viewport-0930，frontend/src/pages/chat-new/、仅 chat 样式和新增浏览器验收；目标为本地 API/WS 替身的桌面/390/320 窄屏交互、重连和迟到响应验证，必要局部修复；后端/移动端/商品 UI 只读。
- 下一步第一件事：处理 Run inbox 的 question/escalation/worker_done，逐任务审查成果与实际测试，再集成本地 main；成功/失败结局均需明确，不凭派发回执判断完成。没有 push、上线部署或真实平台操作。
- 当前执行边界：A 已确认 Windows 与 Ubuntu-24.04 WSL 无现成 MySQL/container，按任务交付隔离测试库 harness，真实 MySQL 不记通过；A 的迁移测试已新增，补丁未落盘或审批中断的测试不记完成。B/C 已按原任务继续，仍有自动审批超时，超时命令不计执行；C 的本地 Node/Vite/Playwright 升级执行请求已通过 Orca reply 明确继续授权，收件批次 delivery_1e298aa9fe69 已处理/ack。三个 Dispatch 尚未返回 worker_done，均保持进行中，集成尚未开始。
- 执行环境阻塞已确认：主协调三条只读升级执行及三个 worker 均返回 automatic permission approval review deadline；依赖检查仅重试一次仍失败。只读读取自动审查最终结果发现一条 outcome=allow，但开始到答复耗时 738.924 秒（约 12 分钟），不能把超时当作未开启 auto_review 或不安全判断。已通知 A/B/C 保留文件/原 Dispatch、不反复重试，新的 question 已回复，delivery_20d609559ea6 与心跳批次已 ack。正在等待用户选择保留自动模式保存停点或临时人工审批；未自行切回人工或更改全局配置。

### 历史：人工核对、HTTP 与双端交互离线阶段收尾（2026-09-30）

本轮来源：用户先按会话摘要要求继续，随后于 15:27 明确要求停止开发、快速收尾；已停止新增业务修改，只维护交接，下一阶段等待新的继续授权。已取得最后一次 Python 全套实际结果，人工核对、HTTP 合同和双端交互回归完成；下架子项已离线验证，R03/R04/R07 整体仍进行中。以下历史额度停点不代表本轮又读取了用量；本轮未取得实际 usage，不能宣称已检查或达到阈值，也未重置或购买额度。

完成内容与关键文件：
- `listing_action_service.py` 的 unknown 人工核对只接受明确的 `offline` / `active` 和非空依据；路由强制 `confirmed=true`。核对记录为 `reconciled`，不改成 failed、不发送平台请求；归属、任务目标和账号边界受校验。
- 新增 nullable `reconciled_conflict` 保存首次核对时的本地版本冲突；相同结论重复调用保留冲突事实，不覆盖后续本地状态；旧记录按既有冲突提示兼容。`listing_action.py` 模型与 `init_database.py` 旧库补字段声明同步，后者包含核对时间 `DATETIME(6)`；真实 MySQL 升级尚未实测。
- `test_offline_api_http.py` 使用真实目标 FastAPI 路由和 service、SQLite 与认证替身。类级模块隔离退出后恢复；导入前禁止真实 session；确定性排程先断言 worker 领取、guard 运行、真实终态和一次平台替身调用，避免 pending 被误当成 unknown。Windows 只放行标准库 `socketpair()` 内部唤醒通道，普通连接、connect_ex 与 DNS 仍被拒绝。
- Web/Android 下架页面补显式详情刷新、跨商品/任务核对表单清理和迟到响应隔离；核对保存成功与后续查询失败分别提示。保存期间暂停详情轮询，结束后恢复；目标不再 unknown 时清理旧表单。确认冻结商品、任务、窗口和目标，轮询不能扩大用户已确认的失败重试范围，失效目标提交前拒绝。
- 新 `test_offline_ui_interactions.cjs` 执行真实组件函数/effect/事件，最终 68 场景通过；不同任务使用不同目标 ID，精确断言核对的 batch/target/state/note/confirmed。子代理以 target+999 内存变异验证双端断言能失败，未把变异写入源码。`Items.tsx` BOM 仅一次且位于 offset 0。
- `test_listing_actions.py` 索引检查改为结构化 inspector，检查队列索引列与 `(batch_id, listing_id)` 唯一约束，不依赖 SQLite 自动索引编号。

最终验证事实：
- 托管 Python 3.13.12、既有隔离依赖下执行 `-B -m unittest discover -s tests -p "test_*.py" -q`：**141/141 通过，0 失败/0 跳过，186.420 秒**。包括 HTTP 合同 18 项及最终冲突回归；此前 140 项一次失败是 SQLite 自动索引编号断言，已修复后完整复跑，不沿用修改前专项结果。
- 六组 Node 离线回归全部通过：聊天加载、重连补拉、Android 聊天（26 场景）、移动发送回执、移动批次存储竞态、下架双端交互（68/68）。Web 与 Android 完整 `tsc --noEmit` 均通过。此为摘要前已读取的最终证据；暂停前追加复跑三项收到完成通知，但输出已无法取回，不把该次通知作为新的通过证据，也未继续重跑。
- 保留可见的 Starlette/httpx 和既有 `datetime.utcnow()` 弃用提示，未隐藏警告或升级依赖掩盖。以上不是完整生产应用启动/JWT、浏览器/真机或平台验收。

剩余边界与下一步：
1. **下一步第一件事是隔离 MySQL 环境实测**：旧库补核对字段、`DATETIME(6)`、队列索引/唯一约束、两 worker 竞争、同商品发布/下架共享协调及重启恢复。当前 PATH 未找到 docker/mysql/mysqld/mariadbd/podman；这不证明机器完全没有数据库。没有连接项目生产配置，未对生产数据试验；环境与限定测试库待提供或明确选择隔离实例。
2. 人工核对、HTTP 合同和 68 场景交互无需重复实现；浏览器/真机、APK 和完整生产鉴权验收仍未完成。
3. 恢复接口尚无已核验适配，不以重新发布替代；接口核验后再接库存延迟下架/恢复及 manual/inventory 原因和状态版本保护。
4. 编辑含图片、擦亮、实体物流、Ubuntu 源码部署和视频协议沿用完整需求，不在本阶段宣称完成；无真实账号、商品、买家消息或订单操作。

提交边界：main / HEAD `1a9c4f9`，index 为空，未 add/commit/push。本轮续接涉及 `common/models/listing_action.py`、`common/services/listing_action_service.py`、`common/db/init_database.py`、`backend-web/app/api/routes/internal_products.py`、双端 OfflineBatches 页面、移动 listing-actions wrapper、`tests/test_listing_actions.py`、`tests/test_offline_api_http.py`、`tests/test_offline_ui_interactions.cjs`、本文、NEXT_AI_PROMPT 和项目日志；下架初始模型/平台适配/生命周期及入口、上一轮 CR04—CR07 聊天修复、`.gitignore`、AGENTS/docs/outputs/构建产物等既有改动全部保留未暂存。不要用普通 git diff 的空输出误认为未跟踪新文件没有实现，也不按整目录暂存。

### 历史：持久下架初始实现及额度阈值停点（2026-09-30，后续状态以上文为准）

用户要求在剩余额度内继续开发，任一用量窗口剩余 10% 时停止开发并调用 project-handoff、生成下一步提示词。本轮阶段检查 primary 剩余 57%→37%→32%→25%→13%→8%；最后检测到已越过阈值即停止新增开发。最后 weekly 剩余约 35%。未调用额度重置、未购买额度。

已完成离线实现（R03/R04 下架子项，整体仍进行中）：
- 三张独立商品操作表 ListingActionBatch/Target/Attempt；基于明确关联商品 ID 创建五档下架任务，按内部商品最小间隔，复用 PublishProductSchedule 协调发布/下架；请求 ID 幂等且禁止相同 ID 改参数。
- 创建时校验账号归属、内部商品关联、在售状态，同账号每批一个商品；历史商品不进入跨账号下架。未解决的 pending/running/unknown 任务阻止另建任务绕过保护。
- worker 接入 lifespan；每次目标租约 120 秒、调用上限 60 秒；最终请求 guard 再查关联/状态版本/账号归属/窗口和商品槽位。进程中断：已发起请求 unknown，不自动重发；未发起 failed，可人工新窗口重试。成功只更新指定关联商品为 manual 下架，版本已改变时保留平台成功但提示同步核对。
- 严格下架适配器使用已有 mtop_call 的 request_guard 单次请求分支，无 token 自动重发；必须取得目标 itemId 对应的布尔结果，空逐项结果、计数推断、畸形响应、网络异常均不冒充成功。
- API：/{product_id}/offline-batches 创建/最近任务，/offline-batches/{batch_id} 详情，/offline-batches/{batch_id}/retry 明确失败新窗口重试。请求必须有 confirmed=true 和显式五档窗口；已创建重试任务的目标禁止再建重复重试。
- Web 商品管理增加 OfflineBatches 面板；Android 商品管理增加“关联商品延迟下架”页面。支持账号/商品选取、全部在售关联项、确认范围与数量、无默认窗口、任务状态轮询、尝试日志、失败项新窗口重试。取消确认不发创建请求；网络重试沿用同一请求 ID。
- 原有历史单件下架入口保留，未把它升级为持久批次或声称旧接口未知结果语义已修复。

本轮验证：
- 新持久下架专项最初 10/10 通过；补充四项保护后，全套 Python `-B -m unittest discover -s tests -p "test_*.py" -q` **103/103 通过，0 失败/0 跳过，170.922 秒**。之后新增 API schema 必填确认/窗口专项 **1/1 通过**；没有再跑一次 104 项全套，不能写成 104/104 全套通过。
- Web `tsc --noEmit -p frontend/tsconfig.json` 与 Android `tsc --noEmit -p xianyu-mobile/tsconfig.json` 均通过；修改的 Python AST 语法及 git diff --check 通过（现有 CRLF 转换提示）。
- SQLite 替身验证归属、历史拒绝、同商品协调、幂等、明确失败重试、未知保护、重启恢复、状态版本过期、窗口过期、晚完成及严格响应；全部阻止真实网络。不把这些证据当作 MySQL 多进程、路由 HTTP 集成、浏览器/真机 UI 或平台验收。

未完成及风险边界（下一轮必须先看）：
1. 恢复接口未找到已核验适配，不用重新发布替代恢复；service 明确拒绝非 offline 操作，两端说明恢复未接入。
2. unknown 的人工对账/解除保护入口尚未实现；未知任务会阻止新任务，必须补经限定平台状态核对后的显式对账流程，禁止直接改成 failed 解锁。
3. MySQL 新表初始化已接线，但未实测旧库升级、DATETIME(6)、多 worker 竞争/锁；新 API 未跑完整 FastAPI HTTP 集成，UI 未做组件/真机交互验收或 APK 构建。
4. Web/Android 任务详情在查询失败时显示错误，但本轮没有补自动错误重试/显式刷新按钮；重新选择任务可查询。端到端幂等、取消确认、快速切商品/任务与失败重试选择仍需专项验证。
5. 库存自动下架/恢复、批量修改含图片、擦亮、物流、Ubuntu 一键部署和视频协议仍未完成，不扩展本阶段完成声明。

提交边界：仍 main / HEAD 1a9c4f9，未 add/commit/push。本轮新增 common/models/listing_action.py、common/services/listing_action_platform.py、listing_action_service.py、tests/test_listing_actions.py、frontend/src/pages/items/OfflineBatches.tsx、xianyu-mobile/api/wrappers/listing-actions.ts、xianyu-mobile/app/(tabs)/mine/offline-batches.tsx；修改模型 exports、数据库初始化、backend-web 生命周期与 internal_products 路由、Web/Android 商品入口/移动路由、本文和 NEXT_AI_PROMPT。上一轮 CR04—CR07 修复仍未提交，既有 .gitignore/AGENTS/docs/outputs 等保留，不打包提交它们。

下一步第一件事：阅读 docs/NEXT_AI_PROMPT.md 最新段，审查本轮下架状态机、API/页面与 MySQL 接线，补未知对账和端到端离线验收；再核验恢复接口并接库存动作。达到阈值后本轮不再修改业务代码。


最新停点（本轮修复）：用户授权修复四项，并要求额度临近耗尽时停止新增修改、执行 project-handoff、生成下一步提示词。本轮 CR04—CR07 均已修复并离线验证；未 git add/commit/push，HEAD 仍为 1a9c4f9。

- CR04：Android 接收后端 event=new_message，按原账号/cid 分发。离线测试覆盖文字、图片、两个账号与非消息事件。
- CR05：Web 快照加载保留已有消息和在途推送，稳定 ID 去重后按时间排序；相同 ID 不再因 replace 被清空。
- CR06：Android 补拉改为现有消息合并最新页，按时间排序；真实 syncLatest 回调离线验证补拉期间推送、游标和 hasMore 保留。
- CR07：每个新平台 ID 最多吸收一个占位，重复回声不再次吸收；失败消息不吸收，不同图片 URI 不靠空文本匹配。文字/快捷短语/图片发送接入确切回执 messageId，回声已到时删除对应占位而不重复添加；无 messageId 保留占位，不猜成功关联。
- 接入图片回执时一并修正实际契约：RN 上传字段 file 改为后端要求的 image，显式传递 FormData，业务/HTTP 失败抛错，返回 messageId/imageUrl 用于占位关联。
- 五组 Node 回归通过：test_chat_message_loading、test_chat_reconnect_repull、test_mobile_chat_reliability（26 场景）、test_mobile_chat_send_receipt（新增）、test_mobile_batch_storage_race。新增 Web 反例与移动 A7/A8/A9/B7 在修复前失败，修复后通过。Web 和 Android 完整 tsc --noEmit 均退出 0；git diff --check 通过，仅既有 CRLF 转换提示。
- 没有修改后端，本轮不重跑无关 Python 全套；未连接真实平台、未发送买家消息、未做 APK/真机/MySQL/Ubuntu 验收。文本兜底关联仍使用有限时间窗口；确切回执优先，缺失回执下不保证完全消除占位。
- 额度检查：开始 5 小时/周剩余约 82%/46%，验证后约 65%/43%；未达本轮采用的约 10% 收尾阈值。本轮因修复范围完成收尾，并非额度耗尽。
- 本轮业务/测试未提交文件：frontend/src/pages/chat-new/ChatNew.tsx、xianyu-mobile/lib/ws.ts、xianyu-mobile/app/(tabs)/messages/[id].tsx、xianyu-mobile/api/wrappers/chat.ts、tests/test_chat_message_loading.cjs、tests/test_mobile_chat_reliability.cjs、新增 tests/test_mobile_chat_send_receipt.cjs；以及本文和 docs/NEXT_AI_PROMPT.md。保留既有 .gitignore、AGENTS.md、docs 等未跟踪工作。
- 下一步：按提示词先核对未提交修复与真实环境验收条件，再实现关联商品下架/恢复持久排程；四项无需重复实现。R13 整体仍进行中，不能将局部离线回归等同完整聊天验收。

以下独立审查记录为修复前快照，CR04—CR07 当前状态以上文为准。

最新停点（2026-09-30 独立审查）：当前用户要求审查并提供下一轮提示词；本轮未修改业务代码、未提交或 push。以下四项已用真实源码的离线替身/函数反例复现，R13 仍进行中：

| ID | 优先级 | 发现与复现 | 修复验收 |
| --- | --- | --- | --- |
| CR04 | P1 | Android ws.ts:141 检查 type，后端标准消息为 event；注入真实格式回调 0 次。既有缺陷，本次提交仍未覆盖 | event 消息按账号/cid 分发一次，覆盖文字/图片和非消息事件 |
| CR05 | P1 | Web ChatNew.tsx:246-270 的 replace 去重先过滤已有 ID，再抛弃已有列表；[m1]+[m1] 返回 [] | 历史加载与推送交错不丢消息，同 ID 仅一次、不同 ID 保留 |
| CR06 | P2 | Android messages/[id].tsx:277 的 syncLatest 反向调用合并；[old] 补 [new] 得 [new,old] | 补拉保持时间正序，历史/分页位置保留，覆盖并发推送 |
| CR07 | P2 | Android messages/[id].tsx:98-103 两条 local 独立匹配同一 real，得到 [real,real] | 一对一占位关联、稳定唯一 key；不同图片/失败态不能误吸收 |

本轮验证：四个既有 Node 专项均 PASS（移动聊天包含 21 场景）；额外四反例全部复现。仅执行离线源码，不访问平台。未重跑 Python 全套、双端 tsc、APK、MySQL 或真机。不要将上一 AI 89/89 结果归为本轮验证。

本轮只修改本文和 docs/NEXT_AI_PROMPT.md；未暂存。下一步先修 CR04—CR07，再开发关联商品下架/恢复的持久排程闭环。详细提示词已更新，旧“排程未提交/lease 尚未验证”说明仅是历史，不能继续按其执行。

以下保留上一 AI 阶段记录；其中残留的未提交描述以本节最新 Git 核对为准。

最新停点（2026-09-29 23:41）：本轮两项专项验证与一期聊天可靠性开发完成，并已按提交边界拆成本地 commit：`35db024`（五档排程持久执行器 + 两项专项验证修复，22 文件）、`fb1d861`（一期聊天可靠性，Web+Android，12 文件）、本次文档更新（随本轮提交）。均在 main，**未 push**（本地领先 origin/main 9 个提交）。未启动真实服务或进行平台操作。用户确认视频协议暂无资料，R12 保留阻塞；v0.5 剩余较多，继续功能开发优先，尚未进入部署收尾。

已提交内容（本轮）：
- `35db024`：含上一 AI 已暂存未提交的五档排程持久执行器（该工作自 18:25 起一直躺在暂存区，经用户确认本轮一并提交），并纳入本轮两项专项验证对应的修复与测试——`product_lease_active` 复位、Android 竞态修复及 `tests/test_mobile_batch_storage_race.cjs`。竞态测试与它验证的修复同提交，便于日后单独回退。
- `fb1d861`：一期聊天可靠性，后端 `chat_new.py`/`im_session_manager.py`、Web `ChatNew.tsx`/`useChatNewWs.ts`、Android `lib/ws.ts`/`messages/[id].tsx`/`messages/index.tsx`，及五个测试文件。

本轮一并更正了交接文档的一个历史问题：工作区完整文档（655 行，含需求确认稿 v0.5 全文附录）此前从未提交，暂存区里一直是 95 行的旧精简版；本轮以工作区完整版为准，避免提交时截断需求原文。

仍未提交的文件：`.gitignore`（新增 `!/AGENTS.md` 反忽略规则）、`AGENTS.md`（协作规则，因反忽略规则现已可纳入版本管理，但本轮未纳入）、`PROJECT_STATE.md`（本文，含完整需求附录）、`.workbuddy/`（本地记忆日志）、`docs/`（NEXT_AI_PROMPT.md 与 project-handoff 技能副本）、`frontend/dist-publish-check/`（构建产物，已被 frontend/.gitignore 忽略）、`outputs/publish-batches-and-review-fixes.patch`（四个已提交功能的补丁副本，main 已包含，不要重复应用）。

- 晚完成使用数据库时间记录，目标/尝试附 schedule_error，汇总说明异常；实际成功保留 success，不能重发。该标记指结果收尾晚于窗口，含后处理时间，不声称精确平台响应时刻。
- 聊天广播采用连接快照、并发发送和单连接超时；清理旧集合时保护新订阅集合。
- 上游历史错误返回失败而非空成功；Web 消息请求按代次和账号/会话隔离，迟到结果/错误/loading 不影响当前会话。
- 本轮两项专项验证结论：`product_lease_active` 复位补丁确为必要——移除复位后测试 `test_durable_publish_batch_service.py` 中的释放后心跳续期用例由通过转为失败，属真实缺陷修复而非冗余；Android `product-publish.tsx` 的清除/持久化竞态补丁按 5 个场景逐一对照补丁前版本证伪，其中场景 1、2、5 在补丁前失败，场景 3、4 补丁前后均通过（属防过度限制/写入丢失的回归护栏，非缺陷捕获）。两处补丁均已在工作区保留并校验 md5 一致。
- 本轮已实现（Web）：`useChatNewWs.ts` 通过 `everConnectedRef` 集合区分首连与重连，仅重连触发补拉，认证失败与账号清理时移除标记；`ChatNew.tsx` 新增 `mergeMessages` 按稳定 `messageId` 去重合并（仅对空 ID 的本地乐观消息保留同文同向 5 秒窄兜底）、`mergeConversations` 保留已分页加载的旧会话、`applySentMessage` 仅在仍处于当前账号+会话时写状态且不为未打开会话创建缓存、`syncLatestMessages` 刷新时不动游标与 hasMore、`handleWsReconnected` 对当前账号走状态、后台账号走各自缓存。
- 本轮已实现（Android 聊天）：`lib/ws.ts` 新增 `onReconnected` 事件与 `everConnected` 集合，仅重连（含前台恢复重建）触发补拉；认证失败与主动断开 `disconnect` 时清除标记，网络掉线走内部重试路径保留标记。`app/(tabs)/messages/[id].tsx` 新增模块级 `mergeMessages`/`isEchoOf`/`isLocalMessage`，乐观占位（`local-` 前缀）被同内容真实回声**原地替换**而非追加，避免自己发的消息显示两条；刷新改为合并（不再整体替换冲掉发送中占位）；历史分页经同一合并去重；新增重连补拉 `syncLatest`（不污染 `cursorRef`/`hasMoreRef`）；`hasMore` 由 ref 提升为 state 使「加载更早的消息」入口随分页耗尽消失；滚动跟随改为以 `atBottomRef` 贴底为条件，上翻历史不再被新消息拉回底部；首屏用 `onLayout` 无动画跳底；发送期间不再 `editable={!sending}` 禁用输入框（会收起键盘、中断连续输入）；头部新增当前账号标识（备注名→显示名→ID 回退）。`app/(tabs)/messages/index.tsx` 新增 `mergeConversations(prev, incoming, 'refresh' | 'append')`，重连补拉保留已翻页会话、同 cid 以服务端字段为准，并加上限 200 防长列表无限增长；订阅重连事件按账号过滤后补拉。
- 尚未解决的聊天项（两端口径一致）：浏览器/真机内真实重连、后台恢复与推送补拉交错时序未实测；后台恢复后的缓存刷新只覆盖已实现路径，未做穷尽验证；移动端其余页面窄屏可用性与 Release APK 真机验收未做。不能把本轮修复当成 #304/#339 全部关闭。

以下为上一 AI 排程阶段的实现与提交边界，历史未验证结论以本轮证据补充：

已实现的行为：

- `window_hours` 在批次、逐目标和尝试中持久化，只接受 `1/3/5/12/24`，Web/Android 创建和失败重试均必须显式选择。
- 创建批次时按 `internal_product_id` 分组生成随机 `scheduled_at`；同商品 N 个账号的最小间隔为 `T/(2N)`，`available_at`、deadline 和排程错误落库。
- `PublishProductSchedule` 以 `owner_id + internal_product_id` 唯一协调同商品跨批次、跨 worker 的商品级 lease 和实际 `request_started_at`；延误时 deferred，不压缩后续间隔；窗口到期明确 failed/timed_out。
- 最终发布 HTTP 请求由 `request_guard` 包住，guard 内最多一次请求；网络/畸形响应/guard 退出异常保留 unknown，token 失败不自动重发；媒体准备在 guard 前完成。
- worker 保留目标 lease、商品 lease、心跳、恢复、容量预留、幂等、成功项不重复和未知结果不自动重发；单项失败或容量不足不阻断其他目标。
- Web 和 Android 展示批次/目标计划、可执行或实际请求时间、截止时间、最小间隔、超时/排程原因；Android 已补明确失败项选择和重新选择五档窗口重试，详情分页与轮询代次隔离，生成请求类型补上 `window_hours`。

本轮负责的未提交文件为后端排程/请求边界、Web/Android 排程 UI 和 API、移动请求类型、相关回归测试及本文本轮交接记录；其中业务文件和测试已暂存，本文暂存版本仍需修正换行后才能提交。`backend-web/app/services/durable_publish_batch_service.py` 的另一处仅在释放后将 `product_lease_active` 复位的未暂存修改，已由本轮专项验证确认为必要修复（移除后释放后心跳续期用例失败），仍保留未暂存，未纳入提交。以下仍是其他交接流程或验证产物，未纳入本轮提交：`.gitignore`、`AGENTS.md`、`docs/`、`.workbuddy/`、`frontend/dist-publish-check/`、`outputs/`。

整个 v0.5 仍未完成；下架、修改含图片、擦亮、物流、Android 完整构建/真机、MySQL 迁移与多进程锁、真实平台验收仍待后续阶段。晚完成缺少标记已由本轮修复并回归；普通未传 `request_guard` 的单品/自动续售路径仍保留历史网络重试语义，尚未修复。

已提交 32fdcf9 的持久商品批量发布：批次/账号/目标/尝试模型、数据库表和租约字段、生命周期 worker、平台调用前日志落库、重启恢复、状态查询、历史任务、逐项目标/尝试详情、仅明确失败项重试，以及 Web 类型和操作界面。

本轮还修正了公共单品发布的 batch_id 日志关联和额度跳过结算，并为库存集成测试补充了隔离模块注册。未启动服务、未连接真实闲鱼账号、未执行真实平台操作。

未纳入本轮功能 commit 的工作区文件：AGENTS.md、docs/、.gitignore 以及由其他交接流程产生的 PROJECT_STATE.md 既有大段内容；这些文件保留在工作树中，不在本轮提交边界内。

持久发布功能文件（下表均已纳入 32fdcf9；后续容量/关联与移动改动见 CR01—CR03 提交记录）：

| 文件 | 当前状态 | 作用 |
| --- | --- | --- |
| backend-web/_bootstrap.py | 本轮修改 | lifespan 启动和停止持久批量 worker |
| backend-web/app/services/durable_publish_batch_service.py | 本轮新增 | 批次领取、租约心跳、恢复、结果收尾、历史与重试 |
| common/models/publish_batch.py | 本轮新增 | 批次、账号、逐项目标和尝试记录 |
| common/models/_exports.py | 本轮修改 | 注册批次模型 |
| common/db/init_database.py | 本轮修改 | 创建批次表并迁移租约字段 |
| common/services/publish_execution_service.py | 本轮修改 | 复用预创建日志、batch_id 关联、平台调用前租约续期 |
| backend-web/app/api/routes/product_publish.py | 本轮修改 | 持久提交、状态、历史、目标详情和失败重试 API |
| frontend/src/api/productPublish.ts | 本轮修改 | 批次历史/目标/重试类型和接口 |
| frontend/src/pages/product-publish/BatchPublish.tsx | 本轮修改 | 历史任务、目标详情、尝试记录、失败项重试 UI |
| tests/test_durable_publish_batch_service.py | 本轮新增 | 持久批次 SQLite 状态转移测试 |
| tests/test_internal_product_service.py | 本轮修改 | 测试隔离模块注册 |

提交边界：仅暂存本轮功能文件，以及在 HEAD 版本 PROJECT_STATE.md 上追加的本轮开发记录。工作树完整文档保留并行审查、需求原文和协作机制，不将其他 AI 的大段文档变化夹带提交。

剩余工作区：.gitignore、AGENTS.md、docs/ 和本文完整交接整理由其他流程创建并保留未提交；.workbuddy/memory 为本地日志；frontend/dist-publish-check 为验证产物；outputs/publish-batches-and-review-fixes.patch 为四个已提交功能的补丁副本，当前 main 已包含，不要重复应用。以上均未加入暂存区。

下一步第一件事：在浏览器内对重连补拉、后台恢复与推送补拉的交错时序做真实验证，并处理移动窄屏可用性（键盘遮挡、滚动定位、发送状态、账号标识），完成后按 docs/NEXT_AI_PROMPT.md 继续下架/恢复/修改含图片/擦亮的五档排程复用；两项专项验证（lease 复位、Android 竞态补丁）已在本轮完成，无需重做。之后 MySQL 多进程、其他商品动作、库存联动、物流、移动构建。仅在当前用户仍授权时按清晰文件/patch 边界提交。

## 6. 验证记录

最新验证（2026-09-30，新会话继续接管）：Python 下架/HTTP 专项 52/52（34.950 秒，0 失败/0 跳过，TEMP 隔离依赖）、双端下架 UI 68/68（真实网络调用 0）、移动聊天回执专项、Android 完整类型检查及暂存 diff 检查通过。上一 Orca 会话的 Python 141/141（112.831 秒）、六组 Node、双端类型检查作为历史证据保留。

历史验证（2026-09-30，人工核对与下架离线阶段）：
- Python 3.13.12 在仓库目录执行 `-B -m unittest discover -s tests -p "test_*.py" -q`，使用既有隔离依赖：141/141 通过，0 失败/0 跳过，186.420 秒。包含真实目标路由 HTTP 合同 18 项；SQLite/认证替身，不是生产启动/JWT/MySQL 验收。
- Node 22.22.2 执行六组 `tests/test_*.cjs` 回归通过：chat_message_loading、chat_reconnect_repull、mobile_chat_reliability、mobile_chat_send_receipt、mobile_batch_storage_race、offline_ui_interactions；下架交互 68/68，移动聊天 26 场景。双端完整 `tsc --noEmit -p frontend/tsconfig.json` / `-p xianyu-mobile/tsconfig.json` 通过，为摘要前已读取结果。
- 续接时 `git diff --check` 退出 0，仅既有 LF/CRLF 提示；文档收尾后再次检查。暂停前追加 Node/tsc 复跑输出未取回，不升级证据；MySQL、多 worker、浏览器/真机、APK、真实平台、Ubuntu 未验收。

以下是历史验证，不覆盖上方最新结果。

本轮验证（2026-09-29 23:41，一期聊天可靠性开发并提交后复核）：

- Python 全套离线：托管 Python 3.13.12 执行 `-B -m unittest discover -s tests -p "test_*.py" -q`，**89/89 通过，0 失败/0 跳过**。三次运行分别为 143.276 秒（开发后）、144.185 秒（Android 改动后）、145.874 秒（**两个 commit 完成后复核**），结果一致（较上轮 86 项新增 3 项：lease 复位后的释放后心跳续期、`product_lease_active` 闸门、晚完成失败结果可重试）。
- Web 类型检查：`tsc --noEmit -p frontend/tsconfig.json` 退出码 0。
- 移动类型检查：`tsc --noEmit`（xianyu-mobile）退出码 0。仍未构建 Release APK、未真机验收。
- Node 离线回归四项全部 PASS：`tests/test_mobile_batch_storage_race.cjs`（Android 清除/持久化竞态隔离）、`tests/test_chat_message_loading.cjs`（迟到成功/失败/loading 不覆盖其他会话 + 5 项去重语义）、`tests/test_chat_reconnect_repull.cjs`（Web 重连补拉与迟到响应作用域隔离 + WS 契约源码断言）、`tests/test_mobile_chat_reliability.cjs`（Android 消息合并 / 重连判别 / 会话列表合并 / 调用点契约，**21 场景**）。四项在**两个 commit 完成后再次复跑，仍全部 PASS**。
- 变异证伪（Android 聊天）：退化 `mergeMessages` 为按 ID 去重后追加 → A2 捕获；首连也触发补拉 → B1—B6 全部捕获；认证失败不清标记 → B3 捕获；主动断开不清标记 → B4 捕获；刷新/分页调用点退回整体替换 → C1 捕获；恢复 `editable={!sending}` → C3 捕获；`hasMore` 退回 ref 并无条件滚底 → C4 捕获。全部变异后源码按备份还原并校验 md5 一致。A4/A5/D2—D4 在退化版本下仍通过，属回归护栏而非缺陷捕获，已用 C 组源码级契约断言补住调用点回归。
- 本轮开发过程中 D 组测试实际捕获了本人新写 `mergeConversations` 的参数方向与字段优先级错误（刷新丢会话、分页错序、最新项不在首位），修正后通过——说明该组用例具备真实发现能力，而非恒真。
- 两项专项验证：`product_lease_active` 复位补丁移除后释放后心跳续期用例失败；Android 竞态补丁按 5 场景对照补丁前版本逐一证伪（场景 1/2/5 补丁前失败，场景 3/4 两版均通过）。
- 未做：MySQL 迁移与多进程 worker、真实时间精度、真实平台操作、浏览器/真机内真实重连与后台恢复时序、移动窄屏其余页面、Release APK 真机、Ubuntu 实测。以上离线结果不等于真实平台验收。

上一轮独立验证（2026-09-29 18:50）：Python 3.13，临时依赖 PYTHONPATH 为 TEMP/xianyu-review-fix-deps 与 TEMP/xianyu-capacity-test-deps；`python -B -m unittest discover -s tests -p "test_*.py" -q` 86/86 通过，0 失败/0 跳过，67.622 秒。先前广播+持久专项 36/36 通过。Web `tsc --noEmit -p frontend/tsconfig.json` 通过；`node tests/test_chat_message_loading.cjs` 通过，验证迟到成功/失败/loading 的会话隔离。`git diff --check` 通过（已有文件 CRLF 提示仍在）。未做 Android 完整构建/MySQL 多进程/真实平台/Ubuntu 实测；没有声称这些已通过。

以下为上一 AI 的阶段验证：

本轮最终离线验证：托管 Python 3.13.12 隔离环境执行 `-B -m unittest discover -s tests -p "test_*.py" -v`，81/81 通过，0 失败、0 跳过，耗时约 98 秒；包含排程/持久执行器 37 项、请求边界/公共执行器 18 项，以及容量、库存、来源、结果等已有回归。先前一次全套运行因执行环境超时被中止，不计为通过。

- 排程与持久执行器专项：37/37 通过，覆盖五档逐商品计划、同商品跨批次 lease、不同商品并行、重启过期、延误 deferred、窗口到期、容量结算、重试新窗口、成功/未知/跳过保护。
- 请求边界与公共执行器专项：18/18 通过，覆盖 guard 拒绝时零 HTTP、最终 HTTP 只发一次、畸形/未知响应保留 unknown、token 失败不重发、guard 退出异常、两个发布器媒体准备后才进入 guard。
- 后端限定文件 `py_compile`：通过；`git diff --check`：通过。
- Web：托管 Node 22.22.2-3 执行 `tsc --noEmit -p frontend/tsconfig.json`：通过。
- Android：三个排程相关文件使用同一 TypeScript 编译器 `transpileModule`：通过；尚未执行完整移动 `tsc`。
- 未启动服务、未连接真实闲鱼账号、未执行真实平台操作、未执行真实 MySQL 初始化或多进程锁验证；以上离线测试不等于真实平台验收。

历史独立审查固定 0f20e1d：22 项通过，库存测试类因缺少 loguru 初始化失败（5 项未执行），另两项 SQLite 缺陷复现成功；详见 CR01—CR03 记录。下列 30/30 为早期开发验证，不能替代最新结果。

- 托管 Python 3.13 隔离环境补齐 SQLAlchemy 2.1.1、aiosqlite 0.22.1、asyncmy 0.2.15、Pillow 12.3.0、aiohttp 3.14.3 等测试依赖；旧测试曾尝试连接 localhost MySQL，被拒绝，随后修正替身；本轮新测试在导入前隔离真实会话与平台依赖。
- 持久批次专项：`python -m unittest tests.test_durable_publish_batch_service -v`，3/3 通过；覆盖精确目标数、过期 pending 日志安全失败、仅失败项重试。
- 内部商品库存专项：`python -m unittest tests.test_internal_product_service -v`，5/5 通过。
- 全套离线测试：`python -m unittest discover -s tests -p "test_*.py" -v`，30/30 通过。
- 后端相关 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- Web：managed Node 22.22.2-3 下 `tsc --noEmit` 和 Vite production build 均通过；构建只有既有 Browserslist 数据过期和动态导入提示。
- 未启动服务、未连接真实闲鱼账号、未执行真实平台操作、未执行真实 MySQL 初始化或多进程锁验证；代码入口和离线测试不等于平台能力已验收。

## 7. 下一步（按依赖顺序）

**最新停点：e2e2953 共同基线已提交，Run run_f7192cc83c24 的三个独立工作树 worker 执行中；下一步处理收件箱、审查验证并集成 main。unknown 人工核对、HTTP 合同、双端交互不重复实现；详情见第 5 节。**

完整可复制提示词：docs/NEXT_AI_PROMPT.md 最新段。CR04—CR07 聊天修复保留未提交。

1. 第一件事：明确隔离 MySQL 测试实例及测试库，验证旧库补字段、DATETIME(6)、索引/唯一约束、两 worker 竞争和发布/下架共享协调；当前 PATH 无可用 MySQL/容器入口，不碰生产配置，不用 SQLite 代替锁证据。
2. 核验恢复接口；没有协议证据就记录阻塞，不以重新发布替代恢复。确认后接库存耗尽/取消延迟动作，区分 manual/inventory 下架原因并保护状态版本。
3. 完成浏览器/Android 真机交互、聊天真实重连/后台恢复与窄屏可用性、完整生产鉴权和 Release APK 验证；须限定环境，不操作真实买家/商品/订单。
4. 批量编辑含图片、擦亮、实体物流、Android 必选功能、AI 文案及通知沿用完整需求；#99 按时区/筛选证据局部修复。
5. R12 视频协议仍待补；#302 浏览器替换保留二期评估，不在一期整体替换。
6. 功能完成后交付 Ubuntu 当前源码的一键部署与首装/升级/备份恢复验收；不拉上游镜像冒充当前定制代码。

提交状态提示：共同基线 `e2e2953` 及此前提交均未 push，本地领先 origin/main 10 个提交。用户未要求 push 前不要推送。

## 8. 持续更新方式

已启用 project-handoff 技能，并由 AGENTS.md 要求每轮主动执行。可携带规则位于 docs/skills/project-handoff/SKILL.md；本次 WorkBuddy 实际加载位置为 C:/Users/zhishang_hu/.workbuddy/skills/project-handoff/SKILL.md。历史 Codex 安装路径保留在交接历史中，不作为本次加载位置。不同 AI 不一定支持技能自动发现，但可直接读取仓库技能。技能由 AI 在正常工作过程中执行，不是后台服务；突然中断无法保证补写，因此重要阶段也要保存。

- 开始：读文档、核对 Git 和代码，纠正过时状态。
- 需求变更：记录稳定 ID、来源、验收标准与变更原因，不静默删除旧约束。
- 结束或暂停：刷新台账、停点、提交边界、验证、阻塞和下一步；重要决策和交接记录追加。
- 提交：文档与相关功能一起提交，不夹带其他人的修改；提交号可记“随本轮提交”，不为自身哈希循环补提交。
- 完成：须有实现位置与验证证据，真实平台验收情况单独说明。

每轮记录模板：

```text
日期 / 本轮目标：
需求 ID 与状态变化：
完成内容 / 关键文件：
实现提交（或未提交）：
验证命令 / 结果 / 跳过项：
未完成内容 / 阻塞原因：
当前停点 / 下一步第一件事：
需求变更或决策及来源：
```

## 9. 交接历史

### 2026-09-30：审批模式生效后继续原 Run

- 来源：用户要求全部智能体启用 Approve for me，指出主协调旧轮仍需审批，并主动中断开启新一轮；原 provider 会话及 transcript 只读。
- 纠正启动遗漏：新 worker 使用原指定启动器并追加 --approve-for-me。三个 worker 实际上下文 auto_review 已核实；主协调新一轮生效配置 auto_review，OC03 已验证。AGENTS.md 和协调任务同步此规则，未改默认配置、账号或权限边界。
- main / 8a60b7f（ahead 11），e2e2953 基线和三个原 Task/Dispatch 保留；A 无隔离 MySQL 按 fallback 交付 harness，B/C 原任务继续。自动审批仍有超时，不等于执行成功或明确拒绝；C 继续升级执行的 question 已回复并 ack。无 worker_done 或集成验证，OC02 仍进行中。
- 本轮尚未新增业务验证/功能提交，主目录仅协作规则和交接文档改动；下一步处理实际 worker 结果并审查验证后集成 main。既有 Python 52/52、Node 下架 68/68、移动回执/tsc 为前一运行轮证据，未冒充本轮新结果。
- 后续检查确认当前阻塞为自动审查响应延迟：主协调只读检查超时，一次重试仍超时；已有自动审查最终 allow 耗时 738.924 秒。用户的执行方式选择仍待回答；没有把任何超时命令记为通过，也未终止 worker、重复派发、集成、push 或部署。
- 本轮最终收尾：B `ctx_2604c8b0648b` 已 `worker_done --outcome failed`，没有部署文件、测试或提交；A `ctx_ce4084de84fb` 已 `worker_done --outcome failed`，仅独立工作树留下未提交 `tests/test_mysql_queue_migrations.py`，两次 Python 回归因基础环境缺 SQLAlchemy 未进入业务断言，真实 MySQL/容器不可用；C `ctx_08415b6833c1` 已 `worker_done --outcome failed`，未改聊天源码，留下未提交 `docs/orca/chat-viewport.md` 与工作树 `PROJECT_STATE.md`，真实浏览器/Playwright、Vite/WS harness、截图、六组 Node 和 Web tsc 均未运行。三个 Dispatch 均未合并 main；B/A 已结算并保留外部工作树，C 已结算并保留外部工作树。
- C 报告确认的只读依赖 junction 位于其工作树 `frontend/node_modules`，目标为主目录既有依赖；未安装依赖、未修改目标。它可作为下一轮恢复线索，不能算浏览器验收。A 的 `tests/test_mysql_queue_migrations.py` 目前只在 worker 工作树，未纳入主目录或提交；其测试暴露当前 `ensure_queue_indexes` 入口尚未有已验证实现，不应直接合并为功能。

### 2026-09-30：新会话继续共同基线

- 用户要求继续上一 Orca 工作，原 provider 会话只读，以当前仓库为准。
- 核对 main / 1a9c4f9，已有 30 个文件暂存，无开发 worker；纠正文档中过时的空 index 与未 add 表述，历史验证与新结果分开。
- 删除新增的 Android 下架页重复 Stack.Screen 注册；Python 下架/HTTP 52/52、下架 UI 68/68、移动聊天回执、Android tsc 和暂存 diff 检查通过。共同基线随本轮提交，随后以明确 SHA 派发指定启动器的独立工作树；无 push、部署或平台操作。
- 阶段保存：共同基线已提交 e2e2953；Run run_f7192cc83c24，A/B/C 三个独立工作树以指定脚本/模型启动并接受 Dispatch，任务与文件归属见第 5 节。用户询问三个分支显示终端，已说明终端运行 Codex worker，不代表派发已完成。等待结果审查集成；主目录仅交接进度未提交。

### 2026-09-30：本轮恢复 Orca 主协调接管

- 用户明确恢复授权并要求实际执行；已完整读取协调任务、需求原文与技能指南，核对 main / 1a9c4f9 和全部既有未提交成果，更新独立工作树协作规则。
- 本轮 Python 141/141、Node 六组、双端完整 tsc 通过，必要 diff 审查完成；暂存检查额外发现新测试文件末尾空行，已最小修正后检查。共同基线随本轮提交，派发尚未开始；下一步基于已验证本地基线创建真实 Orca 并行任务。
- 真实平台操作、push、服务器部署未执行；历史暂停记录保留作为历史，不限制本轮明确授权。

### 2026-09-30 15:27：按用户要求停止开发、快速收尾

- 续接人工核对、HTTP 与双端离线交互：修复重复核对冲突丢失、确认范围随轮询扩大、保存/详情刷新竞态及测试隔离和断言缺口；最新证据见第 5/6 节。
- 最终 Python 全套 141/141 通过，0 失败/0 跳过，186.420 秒；此前已读取六组 Node 通过、双端 tsc 通过、下架交互 68/68。暂停前追加复跑仅有完成通知、输出未取回，不新增通过声明。
- 用户明确要求停止后不再新增业务修改，只更新本文、NEXT_AI_PROMPT 和项目日志；main / HEAD 1a9c4f9，index 为空，未 add/commit/push，保留既有未提交工作和 v0.5 完整原文。
- 下一次获准继续后的第一件事为隔离 MySQL 旧库升级/时间精度/索引/两 worker/共享商品协调验证；恢复协议、库存平台闭环及其他功能仍未完成，未执行真实账号/商品/消息/订单操作。

### 2026-09-30：继续开发持久下架，额度阈值交接

- 按用户指令继续开发至额度检查 primary 剩余 8%（上一检查 13%），即停止新增开发，仅更新交接；weekly 约剩 35%。
- 持久下架模型/worker/严格适配/API/Web/Android 入口已实现待环境验收；103/103 全套离线 + 新增 schema 1/1、双端 tsc 通过。恢复、unknown 对账、MySQL 多进程/真实 UI/平台未完成。
- 未提交未推送，保留上一轮聊天修复及其他工作区文件；project-handoff 已执行，下一轮提示词已更新。

### 2026-09-30：按用户授权修复 CR04—CR07

- 四项修复和发送回执关联已完成；补图片 multipart 字段/失败处理。先运行新增反例确认旧实现失败，再修复验证。
- 五组 Node、双端完整 tsc、diff 检查通过；未执行真实平台或服务端环境验收。文件和证据见第 5 节。
- 读取并执行用户指定本机 project-handoff 技能，更新本文与下一轮提示词。额度尚充足；因本轮修复范围完成收尾，未创建 commit/push。

### 2026-09-30：独立审查与下一轮提示词

- 核对 main / 1a9c4f9；最新排程/聊天/文档三个 commit 已存在，纠正正文旧 HEAD；未修改业务源码、未提交。
- 四组既有 Node 测试通过；独立执行源码复现 CR04—CR07，具体位置、影响与验收见第 5 节和 docs/NEXT_AI_PROMPT.md。
- R13 保持进行中，不认定聊天可靠性已完整完成；后续优先修复，再推进关联商品下架/恢复、库存闭环。视频仍缺协议；Ubuntu 部署仍为后续阶段。
- 本轮 project-handoff 更新已落盘；保留完整需求原文及其他 AI 的工作目录文件。

### 2026-09-29 23:41：两项专项验证与一期聊天可靠性实现（Web + Android，已提交）

- Git：起点 HEAD `02479cd`；经用户确认后本轮按提交边界拆分，均**未 push**。`35db024`（五档排程持久执行器 + 两项专项验证修复，22 文件）——其中五档排程是上一 AI 自 18:25 起留在暂存区的工作，用户明确同意一并提交；`fb1d861`（一期聊天可靠性，12 文件）；本文档更新独立提交，以免与业务改动混在一起。提交按文件归属切分，未用 `git add .`，未混入 `.gitignore`、`AGENTS.md`、`docs/`、`.workbuddy/`、构建产物与补丁副本。首个提交曾遗漏 `tests/test_mobile_batch_storage_race.cjs`，已 `git reset --mixed` 回退后重排（回退前建临时分支锚点核对，确认重排后树与原锚点逐字节等价，仅多出该测试），使竞态测试与它验证的修复同提交。`PROJECT_STATE.md` 的暂存版本是 95 行旧精简版，已 `git restore --staged` 移出，避免提交时截断需求原文附录；本次提交的即工作区完整版（含需求确认稿 v0.5 全文附录）。
- 专项验证（本轮强制要求，不因全套测试通过而豁免）：①`durable_publish_batch_service.py` 的 `product_lease_active` 复位——移除复位语句后 `tests/test_durable_publish_batch_service.py` 中“释放后心跳不得续期”用例由通过转为失败，确认是真实缺陷修复；②Android `product-publish.tsx` 清除/持久化竞态——新建 `tests/test_mobile_batch_storage_race.cjs` 用 TS 编译器抽取真实 `persistRecord`/`clearRecord` 在 Node `vm` 中执行，对照 `git show :xianyu-mobile/...` 的补丁前版本逐场景证伪：场景 1（在途写入被清除抢先删除存储）、场景 2（清除中重复弹确认）、场景 5（在途写入丢失）在补丁前失败；场景 3、4 两版均通过，属防过度限制/序列化丢失的回归护栏。补丁保留并校验 md5 与验证前一致。
- 一期聊天可靠性实现（Web）：`frontend/src/pages/chat-new/useChatNewWs.ts` 新增 `everConnectedRef` 集合区分首连与重连，仅重连触发 `onReconnected` 补拉；`disposeConnection`（保留已连标记）与 `cleanupAccount`（清除标记）拆分；认证失败路径同样清除标记。`frontend/src/pages/chat-new/ChatNew.tsx` 新增 `mergeMessages`（稳定 `messageId` 去重合并，仅空 ID 的本地乐观消息保留同文同向 5 秒窄兜底）、`mergeConversations`（保留已分页旧会话）、`applySentMessage`（仅当前账号+会话写状态，且不为未打开会话创建缓存）、`syncLatestMessages`（刷新不游标污染）、`handleWsReconnected`（当前账号写状态、后台账号写各自缓存）；`loadMessages` 追加用 prepend、刷新用 replace；发送路径在调用时固定账号/会话并在失败时不做会话列表更新。两个合并函数以 `useCallback(..., [])` 包裹，避免每次渲染重建导致注入 effect 反复执行。
- 一期聊天可靠性实现（Android 聊天）：`xianyu-mobile/lib/ws.ts` 新增 `onReconnected` 订阅与 `everConnected` 集合，仅重连（含前台恢复重建连接）触发补拉；认证失败分支与 `disconnect(accountId)` 清除标记，网络掉线走内部重试路径保留标记（否则前台恢复不会补拉）。`xianyu-mobile/app/(tabs)/messages/[id].tsx` 新增模块级 `isLocalMessage`/`isEchoOf`/`mergeMessages`：本地乐观占位（`local-` 前缀或空 ID）被同内容真实回声**原地替换**而非追加，修复自己发送的消息显示两条；刷新路径由整体替换改为合并，避免冲掉发送中占位；历史分页经同一合并去重；新增重连补拉 `syncLatest`（不污染 `cursorRef`/`hasMoreRef`）；`hasMore` 由 ref 提升为 state，使「加载更早的消息」入口随分页耗尽消失；滚动跟随改为以 `atBottomRef` 贴底为条件，上翻历史不再被新消息拽回底部；首屏 `onLayout` 无动画跳底；发送期间不再 `editable={!sending}` 禁用输入框（会收起键盘、打断连续输入）；头部新增账号标识（备注名→显示名→ID 回退）。`xianyu-mobile/app/(tabs)/messages/index.tsx` 新增 `mergeConversations(prev, incoming, 'refresh' | 'append')`，重连补拉保留已翻页会话、同 cid 以服务端字段为准，并加 200 条上限防长列表无限增长；重连订阅按账号过滤后再补拉。
- 测试：新增 `tests/test_chat_reconnect_repull.cjs`（会话合并顺序、消息合并顺序、非当前会话缓存写入且保留 `msgCursor`、不为未打开会话创建缓存、跨账号迟到响应零状态写入、当前会话写入与失败不更新会话、WS 重连契约源码断言）；扩展 `tests/test_chat_message_loading.cjs`（新增 5 项去重语义）；新增 `tests/test_mobile_chat_reliability.cjs`（Android 消息合并、重连判别、会话列表合并、调用点契约，共 21 场景）。
- 验证：Python 全套离线 89/89 通过（143.276 秒，复跑 144.185 秒，**提交后复核 145.874 秒**）；Web `tsc` 退出 0（提交后复跑再次退出 0）；移动 `tsc` 退出 0；四个 Node 离线回归全部 PASS（提交后复跑仍全部 PASS）。Android 侧逐条变异证伪：退化 `mergeMessages`→A2；首连也补拉→B1—B6；认证失败不清标记→B3；主动断开不清标记→B4；刷新/分页调用点退回整体替换→C1；恢复 `editable={!sending}`→C3；`hasMore` 退回 ref 并无条件滚底→C4；每次变异后均按仓库内备份还原并校验 md5 一致，备份目录已清理。A4/A5、D2—D4 在退化版本下仍通过，属回归护栏，已用 C 组源码级契约断言补住调用点回归。本轮新写的 `mergeConversations` 参数方向与字段优先级错误由 D 组测试实际捕获（刷新丢会话、分页错序、最新项不在首位），修正后通过。
- 未做/未验证：浏览器内真实重连、后台恢复与推送补拉交错时序；后台恢复缓存刷新仅覆盖已实现路径；移动窄屏其余页面与 Release APK 真机验收；MySQL 多进程、真实平台、Ubuntu 部署。R13 仍为进行中，不视为 #304/#339 全部关闭。
- 下一轮第一件事：浏览器内重连/后台恢复时序实测 + 移动窄屏可用性；随后按 NEXT_AI_PROMPT 推进下架/恢复/修改含图片/擦亮的五档排程复用。两项专项验证已完成，不要重复做。

### 2026-09-29 18:52：独立审查修复与 Issue 评估

- main / HEAD 02479cd；保留上一 AI 的已暂存五档排程和既有未暂存修改；本轮未 git add/commit/push。
- 修复晚完成未标记、广播集合并发/旧集合清理、IM 历史错误误报成功、Web 切会话迟到响应覆盖四类问题；测试和提交边界见第 5/6 节。
- 86/86 离线测试、Web tsc、聊天加载竞态 Node 回归和 diff 检查通过；不等于 MySQL、APK、真实平台验收。
- 已读 #297/#302/#304/#339/#99 并评估一期/二期及复杂度；R12 用户同意暂记协议阻塞，先推进其他功能。整体仍有多块核心功能，不按部署收尾。
- 下一轮提示词含 Ubuntu 单机源码一键部署要求；脚本尚未新增、服务器尚未部署。project-handoff 已按要求更新。


### 2026-09-29 18:25：用户要求停止代码修改并快速收尾

- 用户明确要求：不要继续改代码，使用 project-handoff 快速收尾。
- 本轮停止前实际状态：`main` / HEAD `02479cd3df2aa411eef709db02a9d96f1c26dafe`；五档排程相关业务文件和测试已暂存，`PROJECT_STATE.md` 为 `MM`，暂存版本因 CRLF 换行转换不能直接提交；未创建 commit，未 push。工作树另有 `.gitignore`、完整交接文档、`.workbuddy/`、`AGENTS.md`、`docs/`、构建产物和补丁等其他未提交内容，均保留。
- 在停止前发现但未继续修复：`_request_guard` 释放商品 lease 后，工作区新增的 `product_lease_active` 复位修正未验证；窗口内发起、窗口外返回尚未单独记录晚完成超时；Android 旧批次清除/异步状态写入与详情选择仍可能有竞态。上述不应写成已解决。
- 已完成证据仍为：托管 Python 3.13.12 全套离线测试 81/81 通过，其中排程/持久 37/37、请求边界/公共执行器 18/18；后端 `py_compile`、Web `tsc --noEmit`、Android 三文件语法转译通过。没有运行本次停止后的新业务测试。
- 下一位 AI 接手第一步：读取 AGENTS.md 和本文，核对 `git status --short`、暂存 diff 与 HEAD；先决定保留/修复未验证边界，再修复交接文档换行并按原授权创建本地 commit（如用户仍要求提交），不 push。

### 2026-09-29：五档排程持久执行器完成（随本轮提交）

- 范围：把五档 `1/3/5/12/24` 接入持久商品发布执行器。新增 `PublishProductSchedule`，按 `owner_id + internal_product_id` 协调跨批次和跨 worker 的实际请求起始时间与商品级 lease；批次/目标/尝试保存窗口、随机计划、可执行时间、deadline、实际请求时间和排程错误。
- 后端：`backend-web/app/services/durable_publish_batch_service.py` 在最终请求前重新校验计划、deadline、target lease 和商品 lease；延误记录 deferred attempt 并重新排队，不压缩计划；窗口到期明确失败/timed_out；保留容量、恢复、幂等、成功/未知保护。`product_publish.py` API 强制窗口字段，重试只接受明确失败项并使用新窗口。
- 请求边界：`common/services/publish_execution_service.py`、两个 publisher 和 `common/services/xianyu_mtop.py` 接入 request guard；最终发布 HTTP 最多一次，网络/畸形响应/guard 退出异常进入 unknown，token 失败不重发，媒体准备在 guard 前完成。
- 客户端：Web 和 Android 增加五档必选、计划/截止/实际请求/超时详情；Android 增加明确失败项选择和新窗口重试，状态结束保存与详情解耦，轮询和详情分页代次/加载状态隔离，移动生成请求类型补 `window_hours`。
- 验证：托管 Python 3.13.12 全套离线 `unittest discover` 81/81 通过；排程/持久 37/37；请求边界/公共执行器 18/18；后端 `py_compile`、Web `tsc --noEmit`、Android 三文件 `transpileModule`、`git diff --check` 通过。未运行服务、真实平台、MySQL 多进程或 Android 完整 tsc/APK/真机。
- 提交边界：仅本轮后端、Web/Android、测试和本条交接记录；未纳入 `.gitignore`、`AGENTS.md`、`docs/`、`.workbuddy/`、`frontend/dist-publish-check/`、`outputs/` 等其他工作区文件；本地 commit 不 push。
- 当前停点：R01/R03 更新为已实现待验证；v0.5 其他商品动作和真实环境验证仍未完成。下一步先补移动依赖做完整 tsc/APK/真机验证，再做 MySQL/多进程验证。

### 2026-09-29：五档排程 Web/Android 只读审查

- 用户范围：仅审查/验证 Web Android 改动；五档 `1/3/5/12/24` 必选、无默认业务选择；失败重试新开窗口且只明确失败；两端详情展示计划/截止/超时；不改代码、不提交、不调用真实服务。
- 实际状态：main / `02479cd`；四个目标文件及相关后端/测试改动均在既有工作区，未将本轮审查混入业务文件。仅更新本交接文档以记录证据。
- 已确认：Web API 与页面提交窗口为 `PublishWindowHours = 1 | 3 | 5 | 12 | 24`，提交和重试均阻止空窗口；后端 `BatchPublishRequest` / `BatchRetryRequest` 使用必填 Literal；Web 详情展示计划、可执行、截止、请求发起、最小间隔和排程错误。Android 提交窗口和详情字段展示已存在，移动 wrapper 的五档参数/错误封装通过内存 mock。
- 发现问题：Android wrapper/页面没有失败目标重试 API、窗口选择或入口，不能满足移动端“失败重试新窗口且只明确失败”；`xianyu-mobile/app/(tabs)/mine/product-publish.tsx:179-205` 先取状态再取详情，详情请求失败会阻止 `finished=true` 的批次持久化为 `finished`，active 记录继续阻塞提交；同文件 `:321-337` 分页与 `:174-212` 轮询共用 `requestGenerationRef`，可复现分页结果被丢弃且 `checking` 永久为 true；`xianyu-mobile/api/generated/types.ts:8585-8596` 的 `BatchPublishRequest` 仍缺 `window_hours`，wrapper 以 `as any` 调用，未形成生成类型约束。
- 离线验证：指定 Node `C:/Users/zhishang_hu/.workbuddy/binaries/node/versions/22.22.2-3/node.exe` 下 `frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json` 通过；移动两个目标文件 `transpileModule` 通过；目标文件 `git diff --check` 通过；内存 mock 验证两端五档提交、Web 五档重试、详情分页/编码、空窗口阻断、业务失败/无效响应拒绝通过；内存顺序复现上述 Android 两个竞态。
- 未验证范围：移动完整 `tsc`/Expo 依赖缺失（`xianyu-mobile/node_modules/expo/tsconfig.base.json` 和移动 TypeScript 均缺失），未构建 APK，未启动服务，未连接真实闲鱼账号，未调用真实服务，未做 MySQL/多进程/真机验收。没有创建 commit 或 push。
- 下一步：修复 Android 失败项新窗口重试、状态与详情解耦、分页/轮询代次隔离，并同步重新生成或补齐移动 OpenAPI 请求类型后重跑完整移动类型检查。


### 2026-09-29：CR01—CR03 独立复核与收尾（随本轮提交）

- 用户授权修复三项并提交，随后确认另一 AI 已完成。核对 main / f258679 后确认修复已分别包含在 807826f（重试保护期）、2ab95e5（成功对账补关联）、f258679（移动历史入口）；复用既有提交，无重复业务改写，不 push。
- 本轮独立验证：Python 3.13，临时隔离依赖补齐 loguru、pydantic-settings，执行 `python -B -m unittest discover -s tests -p "test_*.py" -v`，57/57 通过，0 失败、0 跳过；CR01/CR02 专项另有 15/15 通过。先前缺依赖运行失败及一次主动中止的静默全套运行不计通过，以最终完整结果为准。
- CR03 独立验证：四个修改文件 TypeScript 转译语法通过；内存 mock 调用真实 getXianyuItems/getProductItems，验证默认隐藏、显式开启/关闭历史、账号/分页参数与来源字段映射通过。尚缺 Expo 依赖，未执行完整移动类型检查、APK 构建或真机验证；不把 mock 当成真机验收。
- 状态：CR01/CR02 已离线验证；CR03 代码和接口参数验证通过、完整移动验收待完成。R02/R07/R11 整体仍进行中，三项修复不代表全部业务需求完成。未访问真实平台或 MySQL。
- 提交边界：本轮只提交此独立复核记录；完整工作树交接中的需求附录及其他 AI 整理继续保留。既有 .gitignore、AGENTS.md、docs/、.workbuddy/、frontend/dist-publish-check/、outputs/ 均未暂存。本轮没有业务代码改动。
- 当前停点：三项修复已提交并独立复核完成。下一步补移动依赖进行完整类型/真机验证；产品后续开发仍从五档排程接入持久目标开始，本轮不扩大到排程开发。


以下历史条目的状态以记录当时为准；最新结果以第 3、5、6 节为准。

### 2026-09-29 11:18：用户显式调用交接核对

- 实际核对：main / f258679；四个功能提交均存在，暂存区为空，业务代码没有新增未提交改动。
- 本次只更新交接文档与项目日志，补齐 outputs 补丁说明及实际技能加载路径，保留完整 v0.5 附录、并行审查和既有工作区文件；未新增 commit、未 push。
- 57/57 离线测试及 Web 构建通过来自上一开发轮，本次未重跑；移动完整类型检查/APK、MySQL 多进程及真实平台验收仍未完成。
- 下一步第一项仍为五档排程接入持久目标，跨批次按内部商品约束实际发起间隔；按独立任务本地提交，不 push。

### 2026-09-29：CR03 移动端历史商品入口实现（随本次提交，完整构建待验证）

- 商品管理和卡券商品选择页增加默认关闭的“显示历史商品”，两个 wrapper 显式传 show_history；切换筛选重置分页，旧请求的响应/错误/加载状态均隔离。展示来源及账号，历史行不进入跨账号批量关联，现有单件操作要求选中所属账号。
- 涉及 xianyu-mobile/api/wrappers/items.ts、products.ts 和 app/(tabs)/mine/items.tsx、card-item-relation.tsx，仅四文件。
- 验证：四文件 TypeScript 转译语法及 diff --check 通过；子代理内存 mock 验证参数/分页/竞态/历史保护。主代理完整 tsc 实际失败：TS6053 缺 expo/tsconfig.base；TS5103 借用 Web 的 TypeScript 5.9.3 不支持移动配置 ignoreDeprecations=6.0。移动依赖未安装，未安装替代版本或改配置掩盖问题，未产出 APK。
- CR03 状态为已实现待验证；R07/R11 整体仍进行中。CR02 已独立提交 2ab95e5；CR03 已提交 f258679，不 push。最终 f258679 工作树全套离线 57/57 通过，Web 最新类型检查与生产构建通过。下一步接入按内部商品的五档排程，同时补移动依赖和完整验收。

### 2026-09-29：CR02 人工成功对账关联修复（随本次提交）

- 人工确认发布成功后调用已有幂等商品关联服务，以日志的素材 ID 和精确平台商品 ID 建立内部关联；不再次发布。对账和额度事务先提交，关联失败保留已确认结果，返回单独的 binding_status/binding_message 并在 Web 显示警告。
- 回归验证人工确认成功生成关联、订单正确占用库存、重复补关联不重复建记录，以及关联异常时额度只结算一次、发布成功不回退；库存与额度专项 `-B -m unittest tests.test_internal_product_service tests.test_publish_capacity_service -v` 15/15 通过。Web tsc --noEmit 通过；未做真实 MySQL/平台验收。
- CR01 已提交 807826f；CR02 本次独立提交，未 push。CR03 实现已落盘，完整移动类型检查仍缺依赖，待单独记录提交。

### 2026-09-29：CR01 额度重试保护修复（随本次提交）

- 复用 released 预留时用数据库当前时间刷新 created_at，人工对账的一小时保护期从本次请求起算，不继承旧请求年龄。
- 先前持久发布子任务已本地提交 32fdcf9，未 push；本修复独立提交，仅含容量服务、回归测试及此记录。
- 验证：托管 Python 隔离环境 `-B -m unittest tests.test_publish_capacity_service -v` 8/8 通过，包含两小时前失败预留重新领取后立即人工释放被拒绝；剩余/预留数量保持 2/1。未接真实平台/MySQL。
- CR01 已修复并离线验证；CR02/CR03 继续处理，R02 整体仍进行中。

### 2026-09-29：持久发布子任务完成离线验证（随本轮功能提交）

- 范围：批次/目标/尝试持久化、预创建日志、租约心跳、过期恢复、应用 worker、历史和明细 API、仅明确失败项手动重试。未知目标可吸收日志对账结果；成功结果不因后处理失败变为可重试失败。
- 本轮修正：日志商品 ID 补写；复用预创建日志时保存解析地址；批量忽略素材手工地址并从地址库分配；未知/未完成批次引用的日志不被十天清理删除；人工确认失败清除未确认商品 ID；单项 600 秒执行上限，超时按调用是否发起区分失败或未知，不重发。
- Web：轮询保持分页、任务和请求代次隔离、恢复详情、失败保留任务、尝试时间及日志 ID 展示，终态区分成功/部分完成/失败/未知。
- 验证：托管 Python 3.13 隔离环境 `-B -m unittest discover -s tests -p "test_*.py" -v` 54/54 通过，0 失败/0 跳过；其中持久任务 20、公共发布链路 6、额度 7、库存集成 5。12 个修改/新增 Python 文件 AST 解析通过，git diff --check 通过；托管 Node 22 的 tsc --noEmit 通过，Vite 在 frontend 工作目录输出 dist-publish-check（emptyOutDir=false）成功。
- 首次构建清理旧 dist 被删除保护拦截；独立目录构建通过，未绕过保护。构建保留 Browserslist/Baseline 数据过期和既有动态导入提示。
- 真实边界：未启动完整后端、未执行真实平台操作、未做 MySQL 迁移/多进程实测或 Android Release 构建。旧回合测试曾误尝试本机 MySQL 连接且被拒绝，本轮导入前注入隔离替身。
- R03 整体仍进行中：发布子任务已有实现与离线证据，五档排程和其他动作未接入。旧 30/30 及“完整闭环”表述仅属早期阶段，不代表完整验收。
- Git：main；本轮代码和这段记录随功能提交，不 push；其他 AI 的 AGENTS.md、docs、.gitignore 及工作树完整文档新增内容保留未暂存。下步先处理独立审查 CR01—CR03，再接入排程。

### 2026-09-29：已提交代码独立审查（CR01—CR03）

- 来源：用户要求其他 AI 开发期间只检查已有 commit。固定范围为 main / 0f20e1d767f060975efe8c3d6cf816aac2bfb1cf 相对 1be6493 的重点审查，不代表全部历史代码已审计。只更新本文，不修改、暂存或提交并行开发代码。
- CR01 / P1 / 待修复（R02）：common/services/publish_capacity_service.py:58 复用 released 预留时未刷新 created_at。旧记录超过一小时后再次发布，人工对账按旧时间立即允许释放新请求的额度。SQLite 已复现 freshly retried reservation 被释放，reserved_publish_count=0；新发布仍在途时可导致额度被复用。应按本次尝试起始时间计算保护期。
- CR02 / P2 / 待修复（R02/R05）：同文件 :216—220 人工确认成功只更新日志和额度，绕过 PublishLogService.update_log 的素材关联逻辑。SQLite 已复现 success、material_id=10、InternalProductListing 数量为 0；后续订单事件因无关联被忽略。需幂等补建商品关联，不能重新发布。
- CR03 / P2 / 待修复（R07/R11）：backend-web/app/api/routes/items.py:120 默认 show_history=False，但移动端 wrappers/items.ts:getXianyuItems 和 wrappers/products.ts:getProductItems 均未传此参数，且无显示历史开关。已有历史商品在手机列表消失，纯历史账号列表为空。需补移动端开关及参数。已由固定提交调用链确认。
- 验证：git archive 导出固定 commit 到系统临时目录，用 Python313 和既有 xianyu-capacity-test-deps 执行 python -m unittest discover -s tests -p test_*.py -v：22 项实际测试通过；内部商品测试类 setUpClass 因缺少 loguru 报错，其 5 项未执行，全套未通过。另运行两项上述 SQLite 复现。首次托管解释器与 cp313 依赖不匹配不算业务缺陷。未运行 MySQL、Web/Android 构建或真实平台操作。
- 边界：下文持久批次开发及 30/30 通过是并行开发者记录，不是本轮固定提交验证。工作区已有 .gitignore、PROJECT_STATE.md、持久执行器相关业务与测试改动，以及未跟踪 .workbuddy/、AGENTS.md、docs/ 等均保留。本文是本审查唯一改动，无新增 commit。
- 停点与下一步：审查完成，CR01—CR03 未修复；R02 改为进行中，R07/R11 保持进行中。开发方先修复 CR01，再补 CR02/CR03 回归。保留原持久批次计划，历史提交授权不扩展至本审查。


### 2026-09-28：完成持久商品批量发布闭环（本轮）

- 需求状态：R02、R03 更新为“已实现待验证”；R03 当前只接入商品发布，其他三类商品动作仍待实现。
- 完成：持久批次模型和表、平台调用前日志、租约心跳、过期恢复、未知结果保护、历史/逐项查询、仅失败项重试、Web 入口和离线测试。
- 验证：全套离线测试 30/30、持久批次 3/3、内部库存 5/5；后端语法和 Web 构建通过；无真实平台或 MySQL 验收。
- 提交边界：本轮功能文件待创建本地 commit；不 push。AGENTS.md、docs、.gitignore 及既有交接文档变化不纳入该功能提交。
- 下一步：把 `common/utils/batch_schedule.py` 接入逐目标 `scheduled_at`，再抽象下架、修改含图片和擦亮的持久执行入口。


### 2026-09-28：建立持续交接机制

- 用户要求：跨 AI 保存完整需求和最新进度，每次结束更新 Markdown。
- 完成：保留历史快照，纠正与最新提交不一致的概括；记录既有未提交工作，建立台账、验证边界和更新规则。
- 决策：沿用 PROJECT_STATE.md 为统一入口，不维护多份重复状态文档。
- 当时阻塞：缺少需求确认稿 v0.5 原文；已由下方“恢复原始需求”记录解除。
- 停点：文档机制建立；业务开发下一步核实已有持久执行器接线与验证。

### 2026-09-28：从指定会话恢复原始需求

- 用户提供来源会话链接；读取其消息与引用文件，找到 v0.5 原文及后续接力文档。
- 将 v0.5 全文嵌入附录 B，更新 R01—R11、核心验收清单、后续口径和真正待设计项；无需另发外部文件。
- 保留 main 开发、先离线后真实测试的直接用户选择；区分后续交接记载与原始问答。
- 验证：核对原文完整嵌入及文档差异；没有业务测试、真实平台操作或新的 commit。
- 当前停点：需求原文缺失已解决，业务进度未因补文档而升级；下一步核实持久执行器接线及离线验收。

### 2026-09-28：启用自动交接技能

- 用户要求：把切换 AI 的交接流程做成 skill，AI 完成后自动处理。
- 已创建 project-handoff，开启隐式调用；仓库副本在 docs/skills/project-handoff，本机安装在 C:/Users/zhishang_hu/.codex/skills/project-handoff。
- AGENTS.md 已接入技能：开始核对、阶段保存、结束前自动更新，无需每次提醒。不会自动提交代码，不承诺强制中断后补写。
- 本轮仅修改技能与协作文档，业务状态保持原记录，未新增 commit；下一步业务入口仍为持久执行器接线与离线验收。
- 验证结果：已检查 frontmatter、命名、自动调用配置和项目引用；本机/仓库两份文件 SHA256 一致。官方 quick_validate.py 因缺少 PyYAML 未能运行，未进行新会话自动触发实测；不将文件校验视为自动触发验证。

## 附录 A：原交接快照（历史记录，不代表当前代码状态）

以下仅用于保留来源。涉及“尚未接入数据库”等说法已落后，以前文最新状态及实际源码为准。历史“本会话”不指当前会话。

# PROJECT_STATE

更新时间：2026-09-28

## 开发基线

- 当前开发目录：`D:\Myproject\xianyu-auto-reply`
- 用户确认这是自己刚 fork 并拉取的仓库。
- 基线提交：`1be6493c36f8c66547b91d3940ac32580b1937b9`
- 当前开发分支：`main`（用户明确要求直接在 main 开发）
- 需求依据：用户提供的需求确认稿 v0.5；用户本会话明确要求实现全部需求。旧交接文档中暂停开发的指令已由用户最新要求取代。

## 已确认的实现口径

- 多商品或多批次并行排程时，最小间隔按每个内部商品分别计算。
- 实体物流发货、批量真实执行、共享库存联动和指定 Android 操作仍为目标，不以提醒或卡券发送替代。
- 真实平台验收暂缓；用户会稍后提供限定测试账号、商品和订单。

## 已写入的基础改动

- 聊天的断开、会话、消息读取和发送接口先校验账号归属；发送日志不再包含消息正文。
- 单品及批量发布将平台结果未知与明确失败分开，缺少商品 ID 的“成功”不记为已确认成功。
- 批量发布进度和 Web 日志显示结果未知；进程内快照失效后仅显示已落库日志，不声称批次完成。
- 新增按内部商品分组的五档时间窗口排程算法，以及实际请求延误时的最小间隔检查。尚未接入持久任务执行器。
- 新增内部共享库存的纯状态规则与订单事件去重示例。尚未接入数据库、订单同步和平台上下架。

## 验证

- 标准库测试：14 项通过。
- Web：`npm run build` 通过。
- 修改的 Python 文件语法解析通过。
- 未启动服务、未连接真实闲鱼账号、未执行真实平台操作。
- 本机 Python 缺少 FastAPI、SQLAlchemy 和 pytest；尚无后端集成测试结果。

## 下一阶段必须完成

1. 建立内部商品、账号平台商品 ID、来源类别、剩余额度和库存账本的数据模型及迁移。
2. 建立持久任务批次、逐项目标、尝试记录与可重启执行器；把排程规则接入四类批量操作。
3. 接入商品发布/下架/恢复/编辑含图片/擦亮，保护历史商品并实现逐项状态与仅失败项重试。
4. 接入订单事件与共享库存动作，统一聊天和实体物流发货。
5. 完成 Web 与 Android 操作界面、AI 文案、通知、安全和离线/真实场景验收。

这些项目目前均未完成，不能把基础规则测试视为全部需求已实现。

## 附录 B：需求确认稿 v0.5 原文（完整存档）

以下原文保持原样。其阶段限制、框架未选定等历史状态以本文后续口径和当前用户指令为准；建议与待设计项仍维持原标记。

# 闲鱼多账号管理工具：需求确认稿 v0.5

更新时间：2026-09-20
状态：已合并用户对 v0.4 第十节的七项反馈；供继续审阅，未选定框架或开源底座。

本稿作为当前需求讨论依据；与旧稿冲突时，以本稿及用户最新表达为准。特别是库存恢复条件更新为“可用库存至少 1 件”，不再使用 v0.4 的“大于 1”。业务目标不等于平台能力已经验证。

## 一、核心范围

1. 多个已有闲鱼账号批量上架、下架、修改商品、擦亮；需要实际执行，不用提醒替代。
2. 统一查看各账号买家聊天并回复，明确显示会话所属卖家账号。
3. 查看收货地址，在闲鱼发货流程中填写快递单号、提交发货，展示结果。
4. 集中查看买家信息、主页公开动态、在售商品和评价。
5. 批量操作支持延迟、随机分散执行；提供 AI 文案润色开关，调用用户自己的接口，微调表达以减少文案重复。
6. 移动端支持批量上下架、修改、回复消息、查看买家信息和地址、填写快递单号。
7. 按批量发布时的同一商品建立跨账号关联，维护独立于闲鱼的内部共享库存，拍下、取消驱动自动延迟上下架。
8. 任务中心、执行详情、日志、失败原因、通知和手动重试。

预计使用规模通常不超过 10 个账号，不将其写成不可突破的硬上限。不因此预设复杂多用户或插件系统。

## 二、账号容量：先手动填写剩余额度

### 已确认

- 账号并非新账号，可能已有历史商品；不同账号可发布数量不同。
- 先由用户手动录入“该账号还能上架多少个商品”，不是要求填写总上限。
- 示例：平台总上限 200 个、已有商品 50 个，录入剩余可上架数量 150。
- 是否存在容量读取接口留待后期调研；当前不以自动读取为前提。
- 额度不足或平台返回库存、容量等失败时，记录原因并跳过该项目，继续其他项目。
- 不能为了腾出额度而自动下架历史商品。

### 待设计的实现口径，不作为用户已确认规则

成功发布后如何扣减本地剩余额度、并行任务如何预留额度、下架是否释放平台额度以及平台外操作如何校准，需要在实现阶段明确。本地手工额度不是平台实时事实；不能假设下架一定返还容量。发布失败不能被当作已成功占用。

## 三、统一商品列表与历史商品

### 1. 展示范围

- 提供商品列表，展示本工具发布的商品及能够获取的接入前历史商品。
- 历史商品默认不展示；用户可开启“显示历史商品”。
- 能获取历史数据时，可纳入列表供用户手动下架。
- 展示历史商品不等于把它们加入新批次或库存联动。
- 新批量任务默认不影响历史商品；用户主动选择历史商品下架是明确允许的例外。

### 2. 来源识别

用户希望自动识别历史商品。实现时应结合工具发布记录、平台商品 ID 和接入前数据识别来源，不能仅凭标题相似自动归组。无法可靠识别的商品应标注来源待确认，不自动加入跨账号联动。

本轮未要求把历史商品绑定到新批次；不把“允许查看和手动下架”扩展成“允许自动库存管理”。

### 3. 下架入口

**本工具批量发布、已建立跨账号关联的商品：**

商品后提供下架入口，点击后可选择：

- 批量下架该内部商品在所有关联账号上的商品；
- 指定部分账号下架该商品。

这里的批量范围是所选内部商品的关联账号商品，不是把账号中所有商品下架。

**历史商品：**

- 直接对当前账号的这一个平台商品执行下架；
- 不展示上述“全部关联账号批量下架 / 指定部分账号下架”两个选项；
- 不自动寻找其他账号标题相近的商品进行下架。

### 4. 弹窗确认

用户主动点击下架时，提交前显示确认弹窗，包括商品、目标账号、数量和执行方式，确认后才创建或执行操作；取消弹窗不创建任务。历史商品也需要确认。

此确认用于人工下架入口，不把原有自动库存联动改成每次弹窗审核。

## 四、批量修改与 AI 文案

### 已确认

- 支持批量修改商品，明确包括修改图片。
- 批量上架等操作可通过开关启用 AI 文案微调，主要为不同账号生成表达不同的商品文案。
- 使用用户自己的 AI 接口，协议和具体技术未选定。

### 后续细化或建议

- 标题、描述、价格、运费等修改字段结合需求及平台能力细化；不能把内部库存等同于闲鱼库存字段。
- 图片支持替换、追加、删除或排序中的哪些方式，留到页面设计阶段确认。
- 建议保留原文和最终发布版本，保护品牌、型号、成色等商品事实；不能为了差异化虚构信息。
- AI 无法天然保证不重复；失败或重复文案的处理方式后续细化，不默认使用原文继续发布。
- 不新增 AI 自动回复、自动议价等需求。

## 五、延迟排程与最小间隔

### 已确认规则

- 时间窗口可选：1、3、5、12、24 小时；未指定其中哪一项默认选中。
- 批量上架、下架、修改、擦亮支持延迟和随机分散，在所选窗口内完成。
- 相邻操作间隔不能小于平均时间的一半，不是无约束随机。
- 对用户的“同一商品发布到 N 个账号”示例：窗口 T，平均时间 T/N，最小间隔 T/(2N)。
- 5 个账号、1 小时：平均时间 12 分钟，相邻发布操作间隔至少 6 分钟。

例如在任务开始后的第 4、14、27、39、50 分钟发起 5 次发布，相邻间隔均不少于 6 分钟，且为最后一次操作预留完成时间。这只是合法排程示例，不是固定时间表。

### 实现阶段需明确的边界

- 上述公式首先按一个商品、每个账号发布一次定义；单批多个商品或多个批次同时执行时，间隔按商品组、整批还是全局计算，仍待细化，不擅自决定。
- 单次任务只有一个操作时，没有相邻间隔约束，仍在窗口内执行。
- 建议明确以实际请求发起时刻核验间隔；前项执行延后时，不能为了赶进度把后项挤到不满足最小间隔的位置。
- 容量不足或执行失败后，其他待执行项继续；不要因跳过某项而无条件加速。
- “规定时间内完成”是目标；外部平台异常导致未完成时，需要记录失败或超时未完成，不伪装成功、不静默顺延。
- 人工重试时采用新窗口还是原窗口，后续细化。
- 随机排程不代表不会触发平台限制，不作为防封承诺。

## 六、内部共享库存与自动上下架

### 1. 商品关联和库存定义

同一商品批量发布到多个账号时建立内部商品与账号商品 ID 的对应关系。内部库存由用户维护，与闲鱼商品库存独立，不按标题自动猜测关联。

### 2. 最新确认示例（替换旧阈值）

内部总库存 3 件，同一商品发布到 5 个账号，每单 1 件：

| 事件 | 有效占用 | 可用库存 | 动作 |
|---|---:|---:|---|
| 初始发布 | 0 | 3 | 5 个账号展示该商品 |
| 第 1 个账号被拍下 | 1 | 2 | 不触发库存下架 |
| 第 2 个账号被拍下 | 2 | 1 | 不触发库存下架 |
| 第 3 个账号被拍下 | 3 | 0 | 其余 2 个账号商品触发自动延迟下架 |
| 其中 1 个订单取消 | 2 | 1 | 上述因库存不足自动下架的 2 个商品，触发延迟恢复上架 |

**规则：可用库存耗尽时触发自动下架；取消释放占用后，可用库存 > 0 即满足恢复库存条件。旧稿的“> 1”废止。**

库存变为 1 是订单取消释放占用的结果，不需要等上架成功才改变。总库存仍是 3，不改成 1。恢复两个商品也不等于库存增加两件。

### 3. 恢复对象

- 恢复该内部商品所有因“内部库存不足”而被系统自动下架的关联商品。
- 不是只恢复一个账号，也不是全部账号所有商品。
- 不恢复人工下架、主动停止销售、历史商品或其他原因下架的商品。
- 示例中被买家取消的那个成交账号商品是否恢复，不属于这两个自动下架商品的恢复规则，不额外扩展为恢复全部 5 个账号。
- 人工操作产生的新状态不能被旧的库存恢复任务覆盖。

### 4. 必要的执行检查（实现建议）

- 同一订单通知只计一次；付款不能对已拍下占用的库存重复扣减。
- 延迟下架尚未执行时，若取消使库存恢复，应撤销不再需要的下架任务，而不是先下架再上架。
- 延迟恢复尚未执行时，若库存再次耗尽，应取消不符合条件的恢复任务。
- 已上架的目标不重复提交；任务失败只影响该项，保留原因和日志。
- 多件订单、未付款订单自动关闭、已发货退款和退货入库规则后续细化；退款完成不自动代表实物已可售。
- 延迟下架及同步滞后期间仍可能新增订单，存在超卖风险；不能声称本地库存锁即可阻止平台侧超卖。

## 七、任务中心、日志、通知与重试

### 已确认

- 提供任务列表，例如“发布任务 / 批量上架”。
- 点击详情，查看所有目标账号是否成功，定位到具体账号及商品。
- 展示成功、失败、待执行等状态，失败原因和执行记录可查看。
- 某项发布失败，先忽略该项并继续执行其他项；“忽略”不是删日志或记为成功。
- 有专门的日志查看入口和通知功能。
- 失败项有手动重试按钮，不重跑已经成功的项。

### 建议的信息和保障

- 每批展示目标数、成功数、失败数、跳过数及未完成数；每项展示账号、商品、时间、失败原因及重试记录。
- 重试前检查最新商品状态、容量和库存；保留原失败记录。
- 结果未知的超时单独提示，不因点击重试盲目重复发布或发货；无需当前展开复杂恢复系统。
- 多选失败项批量重试、通知渠道、暂停取消控制等可在页面设计时细化，不擅定为全部已确认。

## 八、聊天、买家信息与发货

### 1. 集中聊天

统一查看各账号所有买家会话并回复，显示账号归属。搜索、标签、备注、快捷话术等作为可选增强，不混入用户已确认核心。

### 2. 买家信息

目标包括买家主页公开动态、在售商品、评价和基本信息。

用户已确认：无法获取时可以忽略对应功能或留白，后续再加，不阻塞其他功能。建议用“暂不可获取”区别于“该买家没有数据”，不伪造内容，也不要求越权访问。

### 3. 发货

查看订单收货地址，在闲鱼发货流程内填写快递单号、提交发货并展示结果。

用户已确认：提交失败先提示失败，暂时忽略，后续遇到再修复；本轮不要求复杂自动补偿或专门的发货重试系统。这不取消批量商品任务的手动重试功能。

记录必要错误信息，避免失败被显示为已发货；超时结果不明不要自动重复提交。快递公司等必填字段按平台后续核验结果确定。

## 九、移动端

用户明确要求的移动端操作：批量上下架、修改商品（包括图片）、回复消息、查看买家信息、查看地址、填写快递单号。

移动端是否同时提供擦亮、完整任务中心和日志，可在页面范围确认时补充；不因旧稿“暂按需要纳入”而认定用户已经确认。手机网页、PWA、独立 App 均未选定。

## 十、当前验收示例

1. 总容量 200、历史商品 50，录入 150 即表示剩余可发布数量，不再减去历史 50。
2. 商品列表默认隐藏历史商品；开启展示后，历史商品可单件下架，弹窗确认，无跨账号批量选项。
3. 工具发布的关联商品点击下架，可选全部关联账号或指定账号；弹窗展示范围，取消不执行。
4. 库存 3、5 个账号，3 单拍下后其余 2 个自动延迟下架；取消 1 单可用库存为 1，这 2 个恢复延迟上架。
5. 5 个账号、1 小时的发布任务，相邻发布间隔至少 6 分钟；异常未完成项在结果中明确标识。
6. 批量修改包含图片；历史商品不被新批次误修改。
7. 某账号容量不足或发布失败，其他账号继续；失败详情能查原因并手动重试，成功项不重复发布。
8. 发货提交失败提示失败；买家公开资料不可获取时留白或提示暂不可用，不阻塞其他流程。

以上为需求验收场景，不表示已有实现或平台可行性核验结果。

## 十一、后续安排与范围边界

本轮不调研接口、不比较仓库、不选择框架，不登录或操作真实账号。

已明确可延后：容量读取接口、历史商品获取能力、买家公开信息获取能力、发货复杂异常修复。

设计阶段再细化：多商品排程的间隔范围、额度更新口径、图片修改方式、重试窗口和售后库存规则。基础安全建议包括凭证保护、日志脱敏、操作追踪和备份，但不扩展为企业级复杂功能。

业务需求确认后，再核验核心平台能力和授权边界，决定是否复用开源项目及采用何种框架。

### 2026-09-30：转入 Orca 多智能体开发

- 用户最新确认允许临时任务分支和独立工作树，成果审查验证后统一合并 main，覆盖此前只在 main 直接开发的协作方式。
- 用户要求实际操作启动；已核对 Orca 1.4.215 可达，独立 Codex CLI 以指定启动脚本、gpt-6.1-sol/xhigh/--no-daemon 在原主工作区就绪。
- 当前仍为 main / 1a9c4f9，既有源码、测试及文档未提交；主协调任务首先审查和整理共同基线，之后才分派最多三个独立开发 worker。完整任务见 docs/ORCA_COORDINATOR_TASK.md。
- 本轮未重跑业务测试，未提交、推送或部署；终端创建首次超时，改为复用已确认空闲主终端，尚未证明任何开发 worker 已启动。后续由 Orca 主协调者更新进展。

### 2026-09-30：用户要求暂停 Orca 协调

- 用户要求先安全保存并暂停，以便恢复会话加载本人修改的配置；已停止派发、环境排查和业务扩展，不退出任何现有进程，不改变审批设置。
- 当前安全停点：仍在 `main` / HEAD `1a9c4f9`，尚未创建 Orca Run、Task、Dispatch 或 worker；共同基线审查已完成，尚未 add/commit。现有源码、测试、交接文档及其他未提交文件全部保留。
- 未提交文件以暂停前 `git status --short` 为准：`.gitignore`、`PROJECT_STATE.md`、后端/前端/移动端聊天与下架改动、`AGENTS.md`、`common/models/listing_action.py`、相关 service/API/UI/test 文件，以及 `.workbuddy/`、`docs/`、`outputs/` 和 `frontend/dist-publish-check/`。未开始新 worker，因此没有 worker 状态可回收。
- 恢复时读取本文件、`AGENTS.md`、`docs/ORCA_COORDINATOR_TASK.md`，核对 `main`、HEAD 和工作区后再决定是否创建 Orca Run。当前 Orca 可用版本为 `1.4.215`；本轮没有取得 Run/Task/Dispatch 会话 ID。主协调会话 ID 未由可用命令返回，恢复应以当前会话继续并重新查询 `orca status --json`，不要猜造 ID。

- 审查进度更正：已读取协调任务与交接规范、核对 Git 并初步审阅必要 diff；完整基线审查、本轮业务验证与提交尚未完成。AGENTS.md 更新尝试因 apply_patch 错误未落盘；本轮未新增业务源码修改。
