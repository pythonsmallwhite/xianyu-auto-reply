# Web 发布后端交接

- 日期：2026-10-16；分支 codex/web-publish-backend；基线 f7c1e1ca18dff2b4e4747f72572df22c5d776123。
- 来源：task_f1d7d3d67278 / ctx_b4caec6ba92c；本轮明确授权完成后提交本分支，不 push。
- 生效权限：approvals_reviewer=auto_review，已通过 Orca 回报；未创建子 agent。
- 当前：R24/R25/R27 已实现待真实环境验证，R26 后端离线已验证；93/93 专项通过。功能和两份交接随本轮提交；下一步主协调审查集成。

## 合同与兼容

- 创建 window_hours 支持 0/1/3/5/12/24，0 去重后单账号；重试 0 限本次选中失败目标的单账号，成功/未知/跳过禁止。
- 0 立即进入持久队列；deadline 为 24 小时执行有效期，不是随机延迟。既有 lease、请求 guard、心跳及恢复保留；立即请求不得绕过之前批次商品间隔。
- address_mode 默认 material，缺地址失败；random 使用既有地址库。xy_publish_batches.address_mode 可空，旧 NULL 保持 random；模型与 MySQL 补列同步。
- 创建和 status 返回 address_mode，重试保持批次策略；重复 batch ID 同参复用、异参拒绝。
- batches page_size=5 原生可用；targets/attempts.finished_at 保持真实收尾时间，不用 created_at/计划时间伪造实际成功时间。

## 视频证据边界

- 已确认：本地 thumbnail_url 抢占新上传封面，再回退 ossUrl 视频地址；修复为强制使用新上传图片。
- 已确认：普通卖家静默清空 videos；修复为明确不支持视频并失败，不调用最终发布。
- 预请求 DirectPublishError 明确失败；网络与最终发布 guard 异常继续 unknown。视频大于三个明确拒绝，避免静默截断。
- opencv-python-headless 已在 backend-web/pyproject.toml；无证据修改 Docker 依赖。发布尝试上限现为 600 秒，保持原值。
- 未取得用户实际线上报错，不能认定本次线上唯一根因；不连接真实平台或生产库。

## 验证与提交

- 初始工作区干净；本轮 13 文件限定提交，不 push；7 个业务/迁移文件、4 个测试和2份交接，不夹带其他 worker 文件。提交号以 worker_done 回报为准，不为文档自身哈希重复提交。
- 只读复用主协调的隔离依赖：`PYTHONPATH=D:/Myproject/xianyu-auto-reply/outputs/r24-test-deps`，`PYTHONIOENCODING=utf-8`。命令：`py -3.13 -B -m unittest tests.test_publish_batch_options tests.test_publish_video_regressions tests.test_durable_publish_batch_service tests.test_publish_execution_service tests.test_publish_guard_boundaries tests.test_publish_capacity_service tests.test_batch_schedule -q`。
- 最终 93/93 通过，0 失败/0 跳过，90.246 秒；11 个改动 Python AST、git diff --check 通过。含8项视频真实函数替身测试；网络/数据库使用离线替身。
- 初次依赖缺 greenlet 失败不计通过；补齐后80项仅旧fixture失败（success/unknown/skipped复用同一商品触发unknown保护），改成独立素材后93项组合全过。
- 在内存运行基线 HEAD 的 `_video_payload` 复现本地缩略图导致平台图片被忽略、oss 视频 URL 冒充封面，修复测试对应断言通过；这证明代码缺陷，不证明本次用户线上失败的唯一原因。
- MySQL 实际迁移/多进程、真实解码与平台视频发布、浏览器/Android 验收均未运行。

## 集成注意

- Web 创建请求默认 material，素材缺地址显示明确错误；需要随机时显式 random。旧队列字段 NULL 无需回填，继续 random。
- 立即执行仍可能因同商品旧批次最小间隔/lease暂缓，24小时期限是执行有效期；不承诺绕过平台限制或马上完成。
- API/schema/服务层均支持0，服务层重试通过真实target账号做单账号校验；不信任客户端提供的账号数量。
- 历史真实成功时间从成功 target/attempt.finished_at 取；batch.finished_at、日志updated_at和计划时间不可替代。
- 无新增历史路由，batches page_size=5已回归；未修改日志分页。
