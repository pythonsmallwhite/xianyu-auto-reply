# 2026-10-14 操作记录

本文记录 2026-10-14 在 `main` 分支上进行的所有代码变更，便于未来对照原作者仓库同步时参考。

---

## 原作者仓库

- 原作者仓库：https://github.com/zhinianboke/xianyu-auto-reply
- 本 fork 仓库：https://github.com/pythonsmallwhite/xianyu-auto-reply
- 同步建议：不要直接 `git merge` 原仓库，改用 `git fetch upstream` 后按 commit 逐一 cherry-pick 或参考修改。

---

## 今日 Commits（按时间顺序）

| Commit | 说明 |
|--------|------|
| `4c0b5a1` | feat(cleanup): R17 删除卡券/自动发货/分销/充值功能（538 文件，-46576 行） |
| `bf37eab` | feat(login): 登录页只保留账号登录，删除极验/邮箱 tab，删除 Google Fonts |
| `f220d30` | fix(deploy): deploy-ubuntu.sh update 场景磁盘要求从 10GB 降至 3GB |
| `9088e7f` | fix(deploy): install-ubuntu.sh --build-only 场景磁盘要求从 10GB 降至 3GB |
| `7cd45bf` | fix(deploy): redis 容器缺少 REDIS_PASSWORD 环境变量导致健康检查失败 |
| `5dfe840` | fix(auth): 删除后端登录接口的极验校验（login_captcha_enabled 默认 true 导致无法登录） |
| `4c9015b` | feat(auth): 删除忘记密码功能（页面、路由、后端 reset-password 端点） |
| `4e2eaff` | feat(ui): 删除使用教程/意见反馈/免责声明/关于/公告管理/弹窗公告，系统改名为"闲鱼管理系统" |

---

## 详细变更说明

### R17：删除卡券与自动发货相关功能（`4c0b5a1`）

**删除的后端模块（`backend-web/app/`）：**
- `api/routes/`: agree_deliver, agree_pickup, card_dock, cards, distribution, payment, refund_cancel
- `services/`: agree_pickup_service, alipay_service, auto_relist_rule_service, auto_relist_serializers, card_dock_service, card_secret_key_service, card_service, dock_record_service, fund_flow_service, order_delivery_query_service, pickup_service, recharge_service, selectable_card_service, selectable_item_service, settlement_service, sub_dock_record_service, withdraw_risk_check

**删除的 common 模块：**
- `common/db/auto_relist_schema.py`
- `common/models/`: agent_order, card, card_dock, card_item_relation, dock_record, withdrawal

**保留的字段（旧库兼容，不 DROP 表）：**
- `xy_accounts` 表中的发货相关列（delivery_disabled 等）保留不用
- `users.secret_key` 保留并改名为"外部接口秘钥"

**前端删除（`frontend/src/`）：**
- 38 个文件（api/cards, api/distribution, api/payment 等，pages/cards, pages/distribution 等）
- 账号管理页：删除发货开关、禁止发货规则、退款注销、同意后发货等 UI 和 API 调用
- 订单页：删除手动发货按钮和发货状态列
- 商品页：删除卡券关联、多数量发货
- 仪表盘：删除总卡券数、今日代销订单统计卡
- 个人设置：删除余额/充值/提现/对接码等区块
- 系统设置：删除支付宝/提现/用户到期配置

**移动端删除（`xianyu-mobile/`）：**
- 删除卡券管理、分销管理相关页面和 API wrapper
- 从 distribution.ts 中抽取 crawler 相关代码到新文件 crawler.ts（crawler 功能保留）
- 账号管理页删除发货相关开关和高级配置入口

**验证：** Web `vite build` ✓，Mobile `tsc --noEmit` ✓

---

### 登录页优化（`bf37eab`）

**`frontend/src/pages/auth/Login.tsx`：**
- 只保留账号+密码登录，删除"邮箱密码"和"验证码"两个 tab
- 删除极验滑动验证码（GeetestCaptcha）组件和相关 state
- 删除"忘记密码"链接

**`frontend/index.html`：**
- 删除 `fonts.googleapis.com` 的 preconnect 和 stylesheet 引用
- 消除因 Google Fonts 请求超时导致的 14s 首屏延迟

---

### 部署脚本修复（`f220d30`、`9088e7f`）

**问题：** `bash deploy.sh` 在磁盘剩余 7.4GB 时报"at least 10 GiB free disk is required"，因为：
1. `deploy-ubuntu.sh` 的 `check_prereqs` 无论 install 还是 update 都要求 10GB
2. `install-ubuntu.sh` 的 `check_os` 在 `--build-only` 模式下也要求 10GB

**修复：**
- `deploy-ubuntu.sh`：有 `.env` 时（更新场景）要求降至 3GB，首次部署仍要求 10GB
- `install-ubuntu.sh`：`--build-only` 时要求降至 3GB，有 `.env` 时也降至 3GB，首次完整安装仍 15GB

---

### Redis 健康检查修复（`7cd45bf`）

**问题：** `docker/ubuntu-compose.yml` 中 Redis 服务没有 `environment` 块，容器内 `REDIS_PASSWORD` 为空，健康检查命令 `redis-cli -a $REDIS_PASSWORD ping` 用空密码连接有密码的 Redis，一直失败。

**修复：** 给 redis 服务加 `environment: REDIS_PASSWORD: ${REDIS_PASSWORD}`。

---

### 后端登录极验校验删除（`5dfe840`）

**问题：** `backend-web/app/api/routes/auth.py` 的登录接口在 `login_captcha_enabled=true`（默认值）时，收到不带极验参数的请求直接返回 `{success: false, message: "请完成滑动验证"}`，导致前端即使删除了极验 UI 也无法登录。

**修复：** 删除 `auth.py` 登录接口中全部极验检查逻辑（两个 if captcha_enabled 块）。

---

### 忘记密码功能删除（`4c9015b`）

- 删除 `frontend/src/pages/auth/ForgotPassword.tsx`
- `App.tsx` 移除路由和 import
- `Login.tsx` 移除"忘记密码?"链接
- `backend-web/app/api/routes/auth.py` 移除 `reset-password` 端点和 `ResetPasswordRequest` 模型

---

### UI 清理与改名（`4e2eaff`）

**删除的页面和路由：**
- 使用教程 (`/tutorial`)
- 意见反馈 (`/feedback`)
- 免责声明 (`/disclaimer`) — 同时删除 `App.tsx` 里的免责声明弹窗逻辑（登录后强制弹窗）
- 关于 (`/about`)
- 公告管理 (`/admin/announcements`)
- 弹窗公告 (`/admin/popup-announcements`)

**全局改名：**
- "闲鱼自动回复管理系统" → "闲鱼管理系统"
- 涉及文件：`frontend/index.html`、`launcher/gui_about.py`、`xianyu-mobile/README.md`

---

## 同步原作者仓库的操作方式

```bash
# 添加上游（只需一次）
git remote add upstream https://github.com/zhinianboke/xianyu-auto-reply
git fetch upstream

# 查看上游新 commit
git log upstream/main --oneline --not main

# 查看某个 commit 的具体改动
git show <commit-sha>

# cherry-pick 单个 commit（如有冲突手动解决）
git cherry-pick <commit-sha>
git cherry-pick --continue  # 解决冲突后继续
```

**同步原则：**
- bug 修复、websocket 稳定性、新闲鱼接口适配：值得同步
- 新增卡券/分销/公告/广告功能：不同步
- 大规模重构：先评估影响范围再决定 cherry-pick 还是重新 fork 后再删
