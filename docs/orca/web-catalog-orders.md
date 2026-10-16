# Web 商品与订单展示交接

- 日期：2026-10-16；任务 `task_768556f1d26a` / Dispatch `ctx_7a0167554dfe`。
- 分支：`codex/web-catalog-orders`；基线 `f7c1e1ca18dff2b4e4747f72572df22c5d776123`，接手工作区干净。
- 实际生效审批：`approvals_reviewer=auto_review`；用户指定模型 `gpt-6-astra`、`xhigh`；未启动子 agent。
- R28 已验证（离线）：默认关闭显示小图，48px 缩略图，IntersectionObserver 加原生图片 lazy；媒体优先视频封面、第一张图片，否则最多2并发 video seek 首帧、6秒超时；失败/无媒体占位，关闭及滚离视口释放视频 src/加载。未用 canvas、自动播放、每行媒体详情接口。
- R29 已验证（离线）：原 item_id/buyer_id 列名称主行、ID副行；240px/180px 最大宽度省略与 title 完整文本；缺名称如实占位。协调补充 msg_c8889b164327 已实现：标题为商品/买家，兼容旧缓存label；独立昵称列可选默认隐藏，旧显式可见配置保留，显示时同样180px省略/title。
- 后端合同：主协调实现 `extract_catalog_media`，`_serialize_item` 返回可选 `item_images`、`item_video_url`、`item_video_cover`；本树不改后端，不从未知 detail 字段猜媒体。没有媒体字段的旧服务显示占位。
- 验证：根目录 `node tests/test_catalog_order_display.cjs` 最终14/14组通过；`node frontend/node_modules/typescript/bin/tsc --noEmit -p frontend/tsconfig.json` 通过；frontend内 `npm run build -- --outDir dist-catalog-orders-check` 通过（2540 modules，既有 autoRate 动静态导入提示）；`git diff --check` 通过。
- 测试执行真实TSX组件/hook/effect与事件，替身隔离API和媒体，覆盖图片lazy/尺寸/失败复位、封面优先/回退、无媒体、无Observer、视频可见性/首帧/短视频/解码失败/异常/超时/队列取消，以及商品和订单原筛选分页勾选详情、旧列缓存与昵称列显隐持久化。最初一次类型检查和两次测试选择器失败修复后重跑，不计为通过证据。
- 提交边界：Items.tsx、ItemThumbnail.tsx、Orders.tsx、types/index.ts、tests/test_catalog_order_display.cjs、PROJECT_STATE.md及本报告，共7文件，随本轮提交；不 push。API wrapper无需修改，后端媒体补丁必须由主协调一起集成。
- 环境：只读依赖 junction 指向 `D:/Myproject/xianyu-auto-reply/frontend/node_modules`，无安装/共享依赖改动；本轮独立构建目录已经清理，无其他遗留未提交文件，junction被忽略并保留。
- 缺口：未运行真实浏览器视觉/视频解码/CDN Range验收；浏览器metadata/seek仍受服务端Range支持影响，限制并发/超时不等于严格字节上限。无真实平台请求。
- 当前停点/下一步：本轮实现与离线验证完成，限定文件commit后向协调者回报SHA；协调者审查集成后安排浏览器及媒体验收。
