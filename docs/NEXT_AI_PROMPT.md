# 下一轮开发提示词

## 最新：2026-09-30 Orca 主协调恢复接管

本轮用户已明确重新授权恢复开发，取代下方历史暂停。执行 `docs/ORCA_COORDINATOR_TASK.md`，以 `PROJECT_STATE.md` 最新停点、实际 main 和 Orca Run/Task/Dispatch 状态为准；先整理已验证共同基线，再基于本地明确 SHA 分派 `codex/` 独立工作树。不得使用旧 origin/main；不自动 push、部署或操作真实平台。

本轮基线验证已完成：Python 141/141、六组 Node、Web/Android 完整类型检查及 diff 检查通过；不是 MySQL、真实浏览器/真机或平台验收。第一轮拟推进隔离 MySQL 迁移/双 worker、Ubuntu 当前源码部署交付、浏览器下架与窄屏验收，按冻结文件边界执行，不重复实现已有人工核对/HTTP/双端交互。

## 历史停点：2026-09-30 15:27 用户要求停止开发、快速收尾

用户明确要求“停止开发快速收尾”；本轮已停止新增业务修改，只保存交接。只有收到新的继续开发授权后才执行下列路线。读取 AGENTS.md、完整 PROJECT_STATE.md 和 docs/skills/project-handoff/SKILL.md，核对 main / HEAD `1a9c4f9814ec1270a46c1420ae0000ca31b8bbd5`、index、工作区和源码；index 为空。保留既有聊天、持久下架、文档和产物改动，不回滚、不全量暂存，未经当前授权不 commit/push。

已经完成，不重复开发：
- unknown 人工核对 service/API/Web/Android 入口，只接受明确 offline/active、非空依据与显式确认；记录 reconciled，不发送平台请求、不改成 failed。重复相同结论保留首次本地版本冲突；nullable reconciled_conflict 模型、旧库补字段声明与旧记录兼容已存在。
- HTTP 测试使用真实目标路由与 service、SQLite 和认证替身；类级模块恢复、网络和真实数据库阻断、确定性排程、真实终态/guard/一次调用断言已补齐。
- 双端显式刷新、跨任务核对清理、迟到响应隔离、保存和刷新错误分离；确认目标范围冻结、保存期间暂停轮询并在结束后恢复、已非 unknown 的旧表单清理。下架交互 68 场景包含精确 batch/target 请求断言和错误目标 ID 内存变异证据。
- 最终 Python 全套 **141/141 通过，0 失败/0 跳过，186.420 秒**；六组 Node 回归通过（下架交互 68/68、移动聊天 26 场景），Web/Android 完整 tsc 通过。后者为本轮摘要前已读取的最终证据；暂停前追加复跑仅有完成通知，输出已无法取回，不额外声明该次通过。Starlette/httpx 与既有 datetime.utcnow 弃用提示仍在。

下一次获准继续后的第一件事：取得或明确创建隔离 MySQL 测试环境，验证旧库核对字段升级、DATETIME(6)、队列索引和唯一约束、两 worker 竞争领取、同商品发布/下架共享协调及重启恢复。PATH 未找到 docker/mysql/mysqld/mariadbd/podman，不等于机器完全没有数据库；不读取或连接生产配置试验。SQLite 与 MySQL 方言 DDL 编译都不能替代 MySQL 实测。

随后核验真实恢复接口，不把重新发布当恢复；有协议证据后再接库存耗尽/取消的延迟动作，保护 manual/inventory 原因和状态版本。编辑含图片、擦亮、实体物流、APK/真机、Ubuntu 源码部署、视频协议仍未完成。浏览器/真机、完整生产启动/JWT、真实平台、MySQL/多进程均未验收，不操作真实账号/商品/消息/订单。

本轮未取得实际 usage，不宣称已检查或触发额度阈值。结束或重要阶段继续更新 PROJECT_STATE.md，原文需求与已有未提交工作必须保留。

---

以下全部是历史提示，以本节最新停点及实际源码为准。

## 历史额度停点：2026-09-30（当时的下一步，已被上方接续结果覆盖）

读取 AGENTS.md、PROJECT_STATE.md、docs/skills/project-handoff/SKILL.md；核对 main / HEAD 1a9c4f9、index 与 diff。上一轮受用户 10% 用量阈值约束，在检查到 5 小时剩余 8% 时停止开发。持久下架已离线实现，仍未提交；不要照下方旧提示重新实现。聊天 CR04—CR07 修复同样未提交。保留既有 .gitignore/AGENTS/docs/输出文件，未经授权不全量暂存或推送。

### 已有实现

common/models/listing_action.py 三表；common/services/listing_action_service.py 状态机和 worker；listing_action_platform.py 严格单次下架；common/db/init_database.py 幂等建新表；backend-web/_bootstrap.py lifespan 接线；internal_products.py 四类 API；Web items/OfflineBatches.tsx 和 Android mine/offline-batches.tsx（商品页入口）及 listing-actions wrapper。

支持：五档显式窗口、关联项范围确认、同商品协调、租约恢复、逐项尝试、ID 幂等、失败新窗口重试、unknown 禁重发。下架成功标记 manual 原因；不是库存自动动作。恢复接口明确未接入。

### 接手优先执行

1. 独立审查新状态机/路由/页面，重点检查锁顺序、guard 最终 HTTP 边界、跨发布/下架协调、重复提交、超时与重启、状态版本变化；不要只相信测试数量。需要改动时先写能失败的回归。
2. 补 unknown 人工核对入口：目前 unknown 会阻止另建任务，但没有对账 API/UI。必须限定账号/商品、显式确认实际平台状态并保存记录，不能把未知自动记 failed 或自动重发。保留实际成功与本地状态变更冲突提示。
3. 补 API HTTP 集成、Web/Android 交互测试：取消确认零请求、无窗口阻断、相同请求 ID 网络重试、快速切商品/任务旧响应隔离、未知/成功禁止重试、查询失败刷新恢复。当前有类型检查，无真实 UI 验收。
4. 在隔离测试库验证 MySQL 旧库升级、新表索引/时间精度、两 worker 竞争领取/商品协调；不得对生产数据试验。SQLite 不能替代 MySQL 锁证据。
5. 核验实际恢复接口，不把重新发布当恢复。可先从现有卖家编辑能力和公开一手协议资料核查；无证据就明确阻塞。接口确认后再接恢复及库存耗尽/取消的延迟动作，沿用状态版本保护和 manual/inventory 原因区分。
6. 后续批量编辑含图片/擦亮、实体物流、APK、Ubuntu 当前源码一键部署、视频协议沿用完整需求。用户没有提供真实测试账号/商品范围，不发送真实消息、不操作真实商品/订单。

### 验证事实

本轮 103/103 Python 全套离线通过，之后新增 schema 专项 1/1 通过，未重跑 104 项全套。双端完整 tsc、修改 Python AST、diff 检查通过。MySQL/多进程、HTTP 集成、浏览器/真机、APK、平台、Ubuntu 均未验收。上一轮五组 Node 聊天回归通过，代码仍在工作树。

关键剩余边界和准确文件清单在 PROJECT_STATE.md 第 5 节最新停点。结束前执行 project-handoff，按实际结果更新；若用户仍要求额度阈值，在阶段边界读取 usage，任一窗口剩余 <=10% 停止新增开发并保存交接。

---

以下为历史提示，以上述最新范围与实际 diff 为准。

## 最新：2026-09-30 四项修复后接手（优先于下方审查和历史计划）

请读取 AGENTS.md、PROJECT_STATE.md 和本提示词，核对 main / HEAD 1a9c4f9 与未提交 diff。CR04—CR07 已由上一轮修复并离线验证，不要重复开发或回滚。业务文件/测试仍未提交，保留 .gitignore、AGENTS.md、docs 和本地输出等其他工作；提交遵循当前用户授权，不 push。

已完成：Android event 推送契约；Web 快照与在途消息合并；Android 补拉正序且保留游标；回声一对一占位关联与确切发送回执。图片上传字段已改为 image，业务失败/HTTP 失败抛错。五组 Node 回归通过（移动聊天 26 场景），Web/Android 完整 tsc 通过。新 tests/test_mobile_chat_send_receipt.cjs 覆盖实际 wrapper 和 syncLatest 回调。未做真机/APK/平台/MySQL/Ubuntu 验收，未重跑无关 Python 全套。

下一阶段请直接执行以下范围：
1. 核对上述未提交修复；若有可用测试环境，验证真实重连、图片上传、回执与推送交错、后台恢复。不自行调用真实买家/订单；无授权环境时记录缺口，继续离线开发。
2. 实现关联商品批量下架/恢复的五档持久排程及 Web/Android 界面，作为独立可交付阶段。复用调度规则，显式 operation 类型与执行适配，不能绕过结果保护。人工操作先展示目标账号/商品确认，取消不建任务；历史商品仅当前账号单件操作。
3. 支持逐项目标/尝试、重启恢复、同商品跨批次间隔、窗口超时记录、未知结果先核对；仅明确失败项新窗口重试，成功不重发。补 MySQL 初始化/迁移和多 worker 并发测试，隔离平台请求。
4. 完成后再接库存耗尽下架和取消恢复闭环。后续修改含图片/擦亮、实体物流、APK、Ubuntu 一键部署沿用下方完整路线；视频协议缺口继续按用户决定暂缓。
5. 若用户仍要求监测额度，在阶段边界读取账户 usage；接近耗尽时停止新增修改，保存实际验证状态、未完成项及下一步，不将未验证功能记为完成。

结束前调用 project-handoff 更新状态，给出实际测试证据、提交边界和下一步。下方 CR04—CR07 是修复前审查证据，不是尚待修复清单。

---

## 2026-09-30 最新审查：优先执行（覆盖下方旧基线与已完成项）

当前 main / HEAD 1a9c4f9。35db024 已提交排程，fb1d861 已提交聊天，1a9c4f9 已提交完整交接。业务工作树干净，不能继续按下方旧“已暂存未提交”状态操作。本轮只审查、更新文档，没有修复代码或提交。请先修以下四项，每项先加能在当前代码失败的回归，再修复；不要仅补源码字符串断言。

1. CR04 / P1：Android 实时推送字段不匹配。xianyu-mobile/lib/ws.ts:141 检查 data.type，实际连接 /api/v1/chat-new/ws；后端 push_message_parser.py:129/168/203 产生 event=new_message，im_session_manager 原样广播。真实 ws.ts 加离线 Socket 后注入 event 包，监听回调实际为 0，期望 1。统一契约，并覆盖文字/图片、不同账号和 cid、非消息事件。该缺陷早已存在，本轮聊天提交仍未修复，不声称是新引入。
2. CR05 / P1：Web mergeMessages 的 replace 模式先用 existing 建 seenIds，过滤掉 incoming 中已有 ID，最后仅返回 accepted。existing=[m1]、incoming=[m1] 实际返回 []。首屏加载期间先收到推送，再收到含相同消息的历史响应，就会删掉该消息；响应没包含的在途推送也会被清掉。修复 ChatNew.tsx:246-270 与 loadMessages 调用，明确快照与在途事件合并边界；验证相同 ID 保留一次、加载中推送保留、同文字不同 ID 不丢、会话隔离不回退。
3. CR06 / P2：Android syncLatest 在 messages/[id].tsx:277 调用 mergeMessages(resp.messages, prev)，把最新页排在旧历史前；prev=[old]、resp=[new] 实际 [new,old]。补拉、首屏与分页要分别覆盖正序合并、重叠分页、补拉响应期间新推送，保留分页游标和阅读位置。
4. CR07 / P2：Android mergeMessages 在 :98-103 对每个 local 独立 find 同一真实回声，local-1/local-2 同内容且时间接近、incoming=[real] 时结果 [real,real]，重复 FlatList key，并丢失另一占位。让占位与真实消息一对一关联，优先用发送回执 messageId；兜底匹配不得吞掉失败消息，不把不同图片（text 都为空）混同。验证两条相同文本、图片、回声先于回执、延迟回声和发送失败。

独立验证：现有四组 Node 专项（test_chat_message_loading、test_chat_reconnect_repull、test_mobile_chat_reliability 的 21 场景、test_mobile_batch_storage_race）均通过，但上述四反例可复现，说明覆盖缺口。既有 89 项 Python 与双端 tsc 为上一 AI 证据，本轮未复跑，不冒充本轮结果。

修复后运行四组 Node + 新反例、Web/移动完整 tsc、涉及后端时运行相关 Python 测试。浏览器/真机联调仅在可用环境与授权范围内进行，不发送真实买家消息。

然后开发一个明确的小阶段：关联商品批量下架与恢复接入五档持久排程，Web/Android 同步提供确认和状态入口；保护历史单件操作、未知结果不重发、仅明确失败新窗口重试。补 MySQL 迁移及两个 worker 并发验证，再接库存耗尽下架/取消恢复。修改含图片、擦亮、实体物流、APK 和 Ubuntu 一键部署仍按下方路线推进；视频协议仍按用户决定暂缓。

更新 PROJECT_STATE.md 后交付修复证据与剩余项；提交遵循当前用户授权，不 push，不纳入其他人的 .gitignore/工作目录产物。

---

以下保留 2026-09-29 的完整范围；基线、已完成项与优先级以上述审查为准。

# 下一轮开发提示词（2026-09-29 审查后）

请直接继续开发本项目，不停留在计划。工作目录 D:/Myproject/xianyu-auto-reply。
先完整阅读 AGENTS.md、PROJECT_STATE.md、docs/skills/project-handoff/SKILL.md，核对 main、HEAD、git status --short、暂存和未暂存 diff。检查时 HEAD 为 02479cd；上一 AI 的五档排程已暂存但尚未提交，本轮审查修复为未暂存。保留既有修改，不执行 git add .，未经当前用户授权不打包提交其他人的文件。

## 最新用户口径

- 继续一期开发，评估下列 GitHub issues；用户将用一台 Ubuntu 云服务器，交付阶段要提供一键部署。
- 视频聊天明确需要，但用户已确认“暂无，先完成其他功能并记录视频协议缺口”。不要猜 contentType 或把商品详情视频上传当成聊天视频发送，不用假成功/仅上传视频链接代替。
- 不进行真实闲鱼账号、商品、消息或发货操作；真实验收等待用户提供限定测试对象与范围。
- 历史 18:25 停工要求已被本轮继续开发要求替代。每个重要阶段更新 PROJECT_STATE.md；测试、构建、真实验收分别记。

## 先完成当前边界，再扩展功能

1. 复核本轮修复和离线测试：
   - durable_publish_batch_service.py：数据库时间记录结果收尾，超过 deadline 单独标记 schedule_error，已成功项不能因此重试；目标/尝试和汇总都可查看。
   - im_session_manager.py：广播遍历快照、单连接发送超时、旧集合清理不能删除新集合。
   - chat_new.py：上游历史消息错误返回 success=False，不返回空成功。
   - ChatNew.tsx：旧会话请求的响应、错误和 loading 不覆盖新会话。
   - tests/test_chat_broadcast.py、test_chat_account_scope.py、test_durable_publish_batch_service.py、test_chat_message_loading.cjs。
   - 另一个 AI 的 product_lease_active 复位和 Android clear/persist 竞态补丁属于此前未暂存工作，需要专门验证，不能仅凭全套测试通过认定这些分支被覆盖。
2. 优先补齐一期聊天可靠性（#304 + #339）：
   - 当前仍缺重连后补拉；后端 WebSocket 心跳正常也不代表上游 IM 正常。补断线状态、重连成功后的会话/消息同步。
   - 最新消息补拉应与实时推送按稳定 messageId 合并去重，保留已加载历史和分页游标；不要用“自己发的同文字五秒内”去重，避免丢失真实重复发送。
   - 缓存恢复后刷新；当前账号的非当前会话也要更新缓存；切账号/会话要隔离会话列表、消息、发送回调的迟到响应。
   - 测试：断网重连、后台恢复、推送和补拉交错、切会话迟到响应、同文字不同 ID、多账号归属、瞬态失败保留消息。
   - 手机窄屏先修可用性（键盘、滚动定位、发送状态、账号标识），不做无关全站重设计；Web 窄屏与原生 Android 分别验收。
3. 验证五档排程后复用到其他商品动作：下架、恢复、修改（含图片）、擦亮。不要将 PublishBatch 硬当通用模型而绕过结果保护；先设计最小 operation 类型与执行适配。
   - 五档窗口必须显式选择；按内部商品 N 账号间隔 T/(2N)，同商品跨批次协调。
   - 历史商品默认隐藏，仅当前账号单件下架并确认；关联商品可选全部/部分账号，取消确认不得创建任务。
   - 未知结果先核对；仅明确失败新窗口重试，不重发成功目标。
4. 补库存平台闭环：库存 3/发布 5 账号，第三单占用后仅剩余关联商品延迟下架；取消后只恢复因库存原因自动下架的目标。人工下架、历史商品不得恢复。幂等和并发订单必测。
5. 补实体物流与 Android 必选功能：查看收货地址、快递公司/单号、真实物流接口；结果未知不自动重复提交。安装项目声明的移动依赖后完整 tsc 和 Release APK，不用转译语法通过代替构建。
6. AI 文案、失败通知、任务日志按 PROJECT_STATE 的已确认范围补齐；未知业务细节不要擅自升级为需求。

## Issue 判断与纳入方式

- #297 https://github.com/zhinianboke/xianyu-auto-reply/issues/297 ：需求合理，当前不支持聊天视频。复杂度中高，协议依赖未解决。R12 阻塞，用户同意先做其他功能。资料就绪后实现文件校验/限额/清理、封面和视频上传、IM 视频发送、历史和推送解析、Web/Android 显示发送状态；回执未知不自动重发，失败不能伪报成功。
- #304 https://github.com/zhinianboke/xianyu-auto-reply/issues/304 ：实时聊天可靠性合理且一期必需，中等复杂度。本轮修了广播和历史请求的确定性缺陷，但不宣称根治所有平台漏消息。
- #339 https://github.com/zhinianboke/xianyu-auto-reply/issues/339 ：消息不显示并入 #304，移动端可用性一期做；完整界面重构延后。整体中等，全面改版中高。
- #99 https://github.com/zhinianboke/xianyu-auto-reply/issues/99 ：时间显示和筛选诉求合理。当前筛选经“查询”按钮提交，前后端已有 processing_status/call_type 过滤；不要重复新增。补筛选分页/总数/归属回归，验证 UTC 与 Asia/Shanghai 数据库环境。created_at 使用数据库 NOW，safe_isoformat 不带时区；先明确存储时区，再局部修复序列化及日期边界，不全局给所有 naive 日期盲加 +08。一期回归/局部修复，低至中等复杂度。
- #302 https://github.com/zhinianboke/xianyu-auto-reply/issues/302 ：可作为后续候选方案；“三行完美迁移、避免风控”不是本项目验证结论。二期独立试验，验证登录、验证码、持久浏览器目录、截图、headless、Docker/Linux 依赖和回退；不要一期全量替换。整体中高复杂度。

## Ubuntu 单机部署阶段（功能完成后交付）

现有 docker-compose.yml 是源码构建，deploy.sh/deploy_remote.sh 偏已有镜像部署。先读脚本，不能拉上游镜像后声称含本地定制功能。

交付一个可重复执行的 scripts/deploy-ubuntu.sh 及文档，基于当前源码/固定自建镜像版本：
- Docker Compose 编排 Web、backend-web、websocket、scheduler、MySQL、Redis；代理支持 WebSocket，HTTPS 入口；不向公网暴露数据库和内部服务。
- 检查 Ubuntu、架构、Docker/Compose、磁盘和端口；首次生成强随机配置，权限 0600；重复执行保留配置和数据，不覆盖凭据，不输出密钥。
- MySQL 时区与应用时间契约一致，数据/上传文件/备份持久化；启动顺序和健康检查明确；禁止默认弱密码部署。
- 固定发布版本，构建当前定制代码；数据库迁移前备份，单实例运行迁移；检查 MySQL 时间精度、唯一键和多 worker 锁。
- 一键安装/更新、查看状态/日志、备份/恢复说明；升级失败保留现场并返回非零，说明应用回滚不等于数据库回滚；不自动删除数据卷。
- 实测干净 Ubuntu 首装、重复执行、升级、重启后任务恢复、WebSocket、备份恢复；shell 语法检查不能等同真实服务器验收。

## 验证和交付

Python 离线全套 unittest discover；Web tsc；node tests/test_chat_message_loading.cjs。测试环境依赖位置是本机临时目录，不能当项目固定运行依赖。MySQL/多进程、移动完整构建与真机、真实平台验证分别报告未完成项。
每次交付给出具体变化、通过/失败/跳过证据和风险；更新 PROJECT_STATE.md 当前停点与下一步，不把这份建议优先级当成用户新增业务需求。
