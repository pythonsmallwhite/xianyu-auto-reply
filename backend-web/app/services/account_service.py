"""
账号服务

功能：
1. 账号CRUD操作
2. 账号状态管理
3. Cookie更新
4. 扫码登录账号创建/更新
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.services.account_limit_service import AccountLimitService
from common.models.xy_account import XYAccount
from common.models.user import User
from common.models.token_cache import TokenCache
from common.utils.cookie_refresh import clear_cookie_refresh_snapshot
from common.utils.xianyu_utils import trans_cookies
from common.utils.time_utils import get_beijing_now_naive

# UTC时区常量
UTC = timezone.utc


class AccountService:
    """Provides access to legacy cookie account records."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_account_options(self, owner_id: int | None = None) -> list[dict]:
        stmt = select(
            XYAccount.id,
            XYAccount.account_id,
            XYAccount.remark,
            XYAccount.status,
            XYAccount.show_browser,
            XYAccount.remaining_publish_capacity,
            XYAccount.reserved_publish_count,
        ).order_by(XYAccount.account_id)
        if owner_id is not None:
            stmt = stmt.where(XYAccount.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return [
            {
                "pk": row.id,
                "id": row.account_id,
                "remark": row.remark or "",
                "enabled": (row.status or "active").strip().lower() not in {"inactive", "disabled", "suspended", "deleted"},
                "show_browser": bool(row.show_browser),
                "remaining_publish_capacity": row.remaining_publish_capacity,
                "reserved_publish_count": row.reserved_publish_count or 0,
            }
            for row in result.all()
        ]

    async def list_account_ids(self, owner_id: int | None = None) -> list[str]:
        """获取账号ID列表，owner_id为None时返回所有账号（管理员）"""
        stmt = select(XYAccount.account_id).order_by(XYAccount.account_id)
        if owner_id is not None:
            stmt = stmt.where(XYAccount.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_accounts(self, owner_id: int | None = None) -> list[XYAccount]:
        """获取账号列表，owner_id为None时返回所有账号（管理员）"""
        stmt = select(XYAccount).order_by(XYAccount.account_id)
        if owner_id is not None:
            stmt = stmt.where(XYAccount.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_accounts_paginated(
        self,
        owner_id: int | None = None,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        ai_reply: bool | None = None,
        scheduled_rate: bool | None = None,
        auto_polish: bool | None = None,
        has_password: bool | None = None,
        disable_reason: str | None = None,
        account_id: str | None = None,
        online: bool | None = None,
        online_account_ids: list[str] | None = None,
        owner_username: str | None = None,
    ) -> tuple[list[XYAccount], int]:
        """获取账号列表（分页），支持多条件筛选
        
        Args:
            owner_id: 用户ID，None表示查询所有用户（管理员）
            page: 页码
            page_size: 每页数量
            status: 状态筛选（active/inactive）
            ai_reply: AI回复开关筛选
            scheduled_rate: 定时补评价筛选
            auto_polish: 商品擦亮筛选
            has_password: 是否配置密码筛选
            disable_reason: 禁用原因模糊搜索关键词（LIKE %keyword%）
            account_id: 账号ID模糊搜索关键词（LIKE %keyword%）
            online: 在线状态筛选（True=仅在线 / False=仅离线 / None=不筛选）
            online_account_ids: 当前在线账号ID集合（口径同仪表盘“在线账号”，由调用方实时取得）

        Returns:
            (账号列表, 总数)
        """
        from sqlalchemy import func, and_, or_
        
        base_stmt = select(XYAccount)
        conditions = []
        
        # 用户ID筛选
        if owner_id is not None:
            conditions.append(XYAccount.owner_id == owner_id)
        
        # 状态筛选 - 与 _status_to_enabled 函数保持一致
        # inactive/disabled/suspended/deleted 视为禁用，其他视为启用
        if status is not None:
            inactive_statuses = ["inactive", "disabled", "suspended", "deleted"]
            if status == "active":
                # 启用：status 不在禁用列表中
                conditions.append(~XYAccount.status.in_(inactive_statuses))
            elif status == "inactive":
                # 禁用：status 在禁用列表中
                conditions.append(XYAccount.status.in_(inactive_statuses))
        
        # AI回复筛选（从metadata_json中获取）
        if ai_reply is not None:
            if ai_reply:
                # AI回复开启：兼容 ai_enabled 与历史 enabled 字段
                conditions.append(
                    or_(
                        XYAccount.metadata_json["ai_reply_settings"]["ai_enabled"].as_boolean() == True,
                        XYAccount.metadata_json["ai_reply_settings"]["enabled"].as_boolean() == True,
                    )
                )
            else:
                # AI回复关闭：metadata_json为空，或 ai_enabled/enabled 都未开启
                conditions.append(
                    or_(
                        XYAccount.metadata_json.is_(None),
                        XYAccount.metadata_json["ai_reply_settings"]["ai_enabled"].as_boolean() == False,
                        XYAccount.metadata_json["ai_reply_settings"]["enabled"].as_boolean() == False,
                        and_(
                            XYAccount.metadata_json["ai_reply_settings"]["ai_enabled"].is_(None),
                            XYAccount.metadata_json["ai_reply_settings"]["enabled"].is_(None),
                        )
                    )
                )
        
        # 定时补评价筛选
        if scheduled_rate is not None:
            conditions.append(XYAccount.scheduled_rate == scheduled_rate)
        
        # 商品擦亮筛选
        if auto_polish is not None:
            conditions.append(XYAccount.auto_polish == auto_polish)
        
        # 禁用原因模糊搜索（忽略空白字符串；ilike 大小写不敏感，自动参数化避免 SQL 注入；与项目其它筛选保持风格一致）
        if disable_reason is not None:
            keyword = disable_reason.strip()
            if keyword:
                conditions.append(XYAccount.disable_reason.ilike(f"%{keyword}%"))
        
        # 账号ID模糊搜索（忽略空白字符串；ilike 自动参数化避免 SQL 注入；与禁用原因模糊搜索保持风格一致）
        if account_id is not None:
            account_id_keyword = account_id.strip()
            if account_id_keyword:
                conditions.append(XYAccount.account_id.ilike(f"%{account_id_keyword}%"))

        # 所属用户名模糊搜索（管理员按账号归属用户筛选）：
        # 账号表无用户名字段，故通过子查询匹配 users.username，再以 owner_id IN (...) 过滤。
        # ilike 自动参数化避免 SQL 注入；普通用户已被上方 owner_id 作用域限制，故此条件不影响数据隔离。
        if owner_username is not None:
            owner_username_keyword = owner_username.strip()
            if owner_username_keyword:
                owner_ids_subq = select(User.id).where(
                    User.username.ilike(f"%{owner_username_keyword}%")
                )
                conditions.append(XYAccount.owner_id.in_(owner_ids_subq))

        # 在线状态筛选：在线集合来自 websocket 实时连接（不在库内），
        # 故以 account_id IN / NOT IN 在线集合 的方式参与 SQL 条件，保证分页正确。
        # 空集合时：online=True 匹配为空（无人在线）；online=False 匹配全部（与语义一致）。
        if online is not None:
            online_ids = [str(x) for x in (online_account_ids or [])]
            if online:
                conditions.append(XYAccount.account_id.in_(online_ids))
            else:
                conditions.append(XYAccount.account_id.notin_(online_ids))
        
        # 是否配置密码筛选（账号和密码都配置了才算已配置）
        if has_password is not None:
            if has_password:
                # 已配置：username和login_password都不为空
                conditions.append(
                    and_(
                        XYAccount.username.isnot(None),
                        XYAccount.username != '',
                        XYAccount.login_password.isnot(None),
                        XYAccount.login_password != ''
                    )
                )
            else:
                # 未配置：username或login_password为空
                conditions.append(
                    or_(
                        XYAccount.username.is_(None),
                        XYAccount.username == '',
                        XYAccount.login_password.is_(None),
                        XYAccount.login_password == ''
                    )
                )
        
        # 应用所有条件
        if conditions:
            base_stmt = base_stmt.where(and_(*conditions))
        
        # 查询总数：直接基于条件统计，避免把整表 SELECT 包进子查询
        count_stmt = select(func.count(XYAccount.id))
        if conditions:
            count_stmt = count_stmt.where(and_(*conditions))
        total_result = await self.session.execute(count_stmt)
        total = total_result.scalar() or 0
        
        # 分页查询：启用账号排在前面，再按创建时间倒序
        from sqlalchemy import case
        inactive_statuses_list = ["inactive", "disabled", "suspended", "deleted"]
        status_order = case(
            (XYAccount.status.in_(inactive_statuses_list), 1),
            else_=0
        )
        offset = (page - 1) * page_size
        stmt = base_stmt.order_by(status_order, XYAccount.created_at.desc()).offset(offset).limit(page_size)
        result = await self.session.execute(stmt)
        
        return list(result.scalars().all()), total

    async def list_all_accounts(self) -> list[XYAccount]:
        """获取所有账号（用于启动时加载）"""
        stmt = select(XYAccount).order_by(XYAccount.account_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_enabled_accounts(self) -> list[XYAccount]:
        """获取所有启用的账号
        
        Returns:
            启用状态的账号列表
        """
        stmt = (
            select(XYAccount)
            .where(XYAccount.status == "active")
            .order_by(XYAccount.account_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_account_for_user(self, owner_id: int | None, account_identifier: str) -> XYAccount | None:
        """
        获取指定用户的账号
        
        Args:
            owner_id: 用户ID，如果为 None 则不限制用户（管理员模式）
            account_identifier: 账号标识（支持 account_id 或 unb）
            
        Returns:
            账号对象，如果不存在则返回 None
        """
        # 先按 account_id 精确查询（account_id 全局唯一，走 uk_account_id 索引），避免 OR 导致索引失效
        stmt = select(XYAccount).where(XYAccount.account_id == account_identifier)
        if owner_id is not None:
            stmt = stmt.where(XYAccount.owner_id == owner_id)
        result = await self.session.execute(stmt)
        account = result.scalars().first()

        # account_id 未命中时，再按 unb 查询（兼容历史数据）
        if account is None:
            stmt2 = select(XYAccount).where(XYAccount.unb == account_identifier)
            if owner_id is not None:
                stmt2 = stmt2.where(XYAccount.owner_id == owner_id)
            result2 = await self.session.execute(stmt2)
            account = result2.scalars().first()

        return account

    async def get_accounts_for_user(self, owner_id: int | None, account_ids: list[str]) -> list[XYAccount]:
        if not account_ids:
            return []
        stmt = select(XYAccount).where(XYAccount.account_id.in_(account_ids))
        if owner_id is not None:
            stmt = stmt.where(XYAccount.owner_id == owner_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_account_by_identifier(self, account_identifier: str) -> XYAccount | None:
        """根据账号标识获取账号（不限制用户，管理员使用）"""
        stmt = select(XYAccount).where(XYAccount.account_id == account_identifier)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def account_id_exists(self, account_id: str, exclude_pk: int | None = None) -> bool:
        """检查 account_id 是否已存在（全局，不区分所属用户）

        Args:
            account_id: 待校验的账号ID
            exclude_pk: 需排除的账号主键（用于更新场景，排除自身）

        Returns:
            True 表示已存在，False 表示不存在
        """
        stmt = select(func.count(XYAccount.id)).where(XYAccount.account_id == account_id)
        if exclude_pk is not None:
            stmt = stmt.where(XYAccount.id != exclude_pk)
        result = await self.session.execute(stmt)
        return (result.scalar() or 0) > 0

    async def create_account(
        self,
        owner_id: int,
        account_id: str,
        cookie_value: str,
        *,
        unb: str | None = None,
        login_method: str = "manual",
    ) -> XYAccount:
        # 全局唯一校验：account_id 不允许与任何用户的账号重复
        if await self.account_id_exists(account_id):
            raise ValueError("账号ID已存在")

        await AccountLimitService(self.session).ensure_can_add_account(owner_id)

        account = XYAccount(
            owner_id=owner_id,
            account_id=account_id,
            cookie=cookie_value,
            login_method=login_method,
            status="active",
            auto_confirm=False,
            pause_duration=10,
            show_browser=False,
            unb=unb,
            last_login_at=datetime.now(tz=UTC),
        )
        self.session.add(account)
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def update_cookie(self, account: XYAccount, value: str) -> None:
        await self._expire_chat_login_cache(account, value)
        account.cookie = value
        account.metadata_json = clear_cookie_refresh_snapshot(account.metadata_json)
        self.session.add(account)
        await self.session.commit()
        await self._disconnect_chat_client(account.account_id)

    async def update_status(self, account: XYAccount, enabled: bool, disable_reason: str | None = None) -> None:
        """更新账号状态
        
        Args:
            account: 账号对象
            enabled: 是否启用
            disable_reason: 禁用原因（仅在禁用时有效，启用时会清空）
        """
        account.status = "active" if enabled else "disabled"
        # 启用时清空禁用原因，禁用时设置禁用原因
        account.disable_reason = None if enabled else disable_reason
        self.session.add(account)
        await self.session.commit()

    async def update_remark(self, account: XYAccount, remark: str) -> None:
        account.remark = remark
        self.session.add(account)
        await self.session.commit()

    async def update_publish_capacity(self, account: XYAccount, remaining: int) -> bool:
        """Set the observed remaining allowance without releasing in-flight holds."""
        result = await self.session.execute(
            update(XYAccount)
            .where(XYAccount.id == account.id, XYAccount.reserved_publish_count <= remaining)
            .values(remaining_publish_capacity=remaining)
        )
        if result.rowcount != 1:
            await self.session.rollback()
            return False
        await self.session.commit()
        await self.session.refresh(account)
        return True

    async def update_pause_duration(self, account: XYAccount, duration: int) -> None:
        account.pause_duration = duration
        self.session.add(account)
        await self.session.commit()

    async def update_message_expire_time(self, account: XYAccount, expire_time: int) -> None:
        """更新相同消息等待时间"""
        account.message_expire_time = expire_time
        self.session.add(account)
        await self.session.commit()

    async def update_reply_delay(self, account: XYAccount, delay_seconds: int) -> None:
        """更新自动回复延迟时间(秒)"""
        account.reply_delay_seconds = delay_seconds
        self.session.add(account)
        await self.session.commit()

    async def update_login_info(
        self,
        account: XYAccount,
        username: str | None = None,
        login_password: str | None = None,
        show_browser: bool | None = None,
    ) -> None:
        """更新账号登录信息（用户名、密码、是否显示浏览器）"""
        if username is not None:
            account.username = username
        if login_password is not None:
            account.login_password = login_password
        if show_browser is not None:
            account.show_browser = show_browser
        self.session.add(account)
        await self.session.commit()

    async def update_scheduled_rate(self, account: XYAccount, scheduled_rate: bool) -> None:
        """更新定时补评价开关"""
        account.scheduled_rate = scheduled_rate
        self.session.add(account)
        await self.session.commit()

    async def delete_account(self, account: XYAccount) -> None:
        await self._expire_chat_login_cache(account)
        await self.session.delete(account)
        await self.session.commit()
        await self._disconnect_chat_client(account.account_id)

    async def get_account_by_unb(self, owner_id: int, unb: str) -> XYAccount | None:
        stmt = select(XYAccount).where(
            XYAccount.owner_id == owner_id,
            XYAccount.unb == unb,
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def _expire_chat_login_cache(self, account: XYAccount, new_cookie: str = "") -> None:
        """Invalidate only this login's chat cache in the account transaction."""
        users = {str(account.unb or "").strip()}
        for cookie in (account.cookie or "", new_cookie):
            users.add(str(trans_cookies(cookie).get("unb") or "").strip())
        keys = [f"chat_{user}" for user in users if user]
        if keys:
            now = get_beijing_now_naive()
            await self.session.execute(update(TokenCache).where(TokenCache.user_id.in_(keys)).values(
                token="", device_id="", expire_at=now, renew_expire_at=now, updated_at=now,
            ))

    @staticmethod
    async def _disconnect_chat_client(account_id: str) -> None:
        from app.services.chat_new.im_session_manager import get_im_session_manager
        await get_im_session_manager().disconnect(account_id)

    async def _generate_unique_account_id(self, owner_id: int, base: str) -> str:
        # 全局唯一：account_id 在整个系统内不允许重复，生成候选时不区分 owner_id
        normalized = base or f"qr_{int(datetime.utcnow().timestamp())}"
        stmt = select(XYAccount.account_id)
        result = await self.session.execute(stmt)
        existing_ids = set(result.scalars().all())
        candidate = normalized
        counter = 1
        while candidate in existing_ids:
            candidate = f"{normalized}_{counter}"
            counter += 1
        return candidate

    async def upsert_account_from_qr(
        self,
        owner_id: int,
        cookies: str,
        unb: str | None,
        *,
        login_method: str = "qr_scan",
    ) -> tuple[XYAccount, bool]:
        account: XYAccount | None = None
        if unb:
            account = await self.get_account_by_unb(owner_id, unb)

        created = False
        if account:
            await self._expire_chat_login_cache(account, cookies)
            account.cookie = cookies
            account.metadata_json = clear_cookie_refresh_snapshot(account.metadata_json)
            account.status = "active"
            account.disable_reason = None  # 清空禁用原因
            account.login_method = login_method
            account.unb = unb
            account.last_login_at = datetime.now(tz=UTC)
            if hasattr(account, "updated_at"):
                account.updated_at = datetime.now(tz=UTC)
        else:
            await AccountLimitService(self.session).ensure_can_add_account(owner_id)
            base_id = unb or f"qr_{int(datetime.utcnow().timestamp())}"
            new_id = await self._generate_unique_account_id(owner_id, base_id)
            account = XYAccount(
                owner_id=owner_id,
                account_id=new_id,
                cookie=cookies,
                login_method=login_method,
                status="active",
                auto_confirm=False,
                pause_duration=10,
                show_browser=False,
                unb=unb,
                last_login_at=datetime.now(tz=UTC),
                created_at=datetime.now(tz=UTC),
                updated_at=datetime.now(tz=UTC),
            )
            self.session.add(account)
            created = True

        self.session.add(account)
        if created:
            await self._expire_chat_login_cache(account, cookies)
        await self.session.commit()
        if created:
            await self.session.refresh(account)
        await self._disconnect_chat_client(account.account_id)
        return account, created

    async def upsert_account_from_password(
        self,
        owner_id: int,
        account_id: str,
        account: str,
        password: str,
        cookies: str,
        unb: str | None,
        show_browser: bool = False,
    ) -> tuple[XYAccount, bool]:
        """协议化账号密码登录成功后保存账号（按前端传入的 account_id upsert）。

        与扫码登录 upsert_account_from_qr 的差异：按 account_id（非 unb）定位，
        并保存 username/login_password/show_browser/login_method='password'。

        Args:
            owner_id: 所属用户ID
            account_id: 前端传入的业务账号ID（定位键）
            account: 登录账号（手机号/邮箱），写入 username
            password: 明文登录密码，写入 login_password（供后台自动刷新复用）
            cookies: 登录成功后的 Cookie 字符串
            unb: 从 Cookie 提取的 unb
            show_browser: 是否有头模式（沿用请求传入值）
        Returns:
            (账号对象, 是否新建)
        Raises:
            ValueError: account_id 已被其他用户占用
        """
        existing = await self.get_account_by_identifier(account_id)
        # account_id 已被其他用户占用时禁止覆盖，直接报错（与 websocket 版一致）
        if existing and existing.owner_id != owner_id:
            raise ValueError(f"账号ID {account_id} 已被其他用户占用，无法登录")

        now = datetime.now(tz=UTC)
        created = False
        if existing:
            existing.cookie = cookies
            existing.metadata_json = clear_cookie_refresh_snapshot(existing.metadata_json)
            existing.username = account
            existing.login_password = password
            existing.show_browser = show_browser
            existing.login_method = "password"
            existing.status = "active"
            existing.disable_reason = None
            existing.last_login_at = now
            if unb:
                existing.unb = unb
            if hasattr(existing, "updated_at"):
                existing.updated_at = now
            account_obj = existing
        else:
            await AccountLimitService(self.session).ensure_can_add_account(owner_id)
            account_obj = XYAccount(
                owner_id=owner_id,
                account_id=account_id,
                cookie=cookies,
                username=account,
                login_password=password,
                show_browser=show_browser,
                login_method="password",
                status="active",
                auto_confirm=False,
                pause_duration=10,
                unb=unb,
                last_login_at=now,
                created_at=now,
                updated_at=now,
            )
            created = True

        self.session.add(account_obj)
        await self.session.commit()
        if created:
            await self.session.refresh(account_obj)
        return account_obj, created

    async def update_auto_polish(self, account: XYAccount, auto_polish: bool) -> None:
        """更新商品自动擦亮开关"""
        account.auto_polish = auto_polish
        self.session.add(account)
        await self.session.commit()

    async def update_auto_red_flower(self, account: XYAccount, auto_red_flower: bool) -> None:
        """更新自动求小红花开关
        
        使用显式 UPDATE SQL 写入，避开 ORM 脏状态追踪可能的陷阱，
        确保操作一定会发送 UPDATE 语句到数据库。
        """
        stmt = (
            update(XYAccount)
            .where(XYAccount.id == account.id)
            .values(auto_red_flower=auto_red_flower)
        )
        await self.session.execute(stmt)
        await self.session.commit()
        # 同步内存对象属性（expire_on_commit=False 下对象属性不会自动刷新）
        account.auto_red_flower = auto_red_flower

    async def update_ai_reply_block_ordered_users(self, account: XYAccount, ai_reply_block_ordered_users: bool) -> None:
        """更新已下单用户禁止AI回复开关
        
        使用显式 UPDATE SQL 写入，确保操作一定会发送 UPDATE 语句到数据库。
        
        Args:
            account: 账号对象
            ai_reply_block_ordered_users: 是否禁止对已下单用户进行AI回复
        """
        stmt = (
            update(XYAccount)
            .where(XYAccount.id == account.id)
            .values(ai_reply_block_ordered_users=ai_reply_block_ordered_users)
        )
        await self.session.execute(stmt)
        await self.session.commit()
        # 同步内存对象属性（expire_on_commit=False 下对象属性不会自动刷新）
        account.ai_reply_block_ordered_users = ai_reply_block_ordered_users
