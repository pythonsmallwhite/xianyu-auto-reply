"""
WebSocket服务内部API路由

功能：
1. 提供账号任务管理接口(启动/停止/重启)
2. 提供任务状态查询接口
3. 提供消息发送接口
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from common.services.account_cookie_service import merge_account_cookie_fields
from common.services.captcha.concurrency import run_browser_task
from common.services.captcha.slider_mode import (
    SLIDER_MODE_REAL_MOUSE,
    refresh_slider_mode_from_database,
)
from common.services.captcha.weighted_runner import real_mouse_weighted_runner
from common.services.im_token_api import (
    extract_im_access_token,
    request_im_token_with_fallback,
)
from common.services.risk_control_log_query_service import (
    check_account_processing_risk_control_log,
    get_account_risk_control_lock,
)
from common.services.token_renewal_cache_service import (
    delete_token_cache,
    mark_token_cache_expired,
    upsert_token_cache,
    write_renewed_token_cache,
)
from common.services.token_api_mode import load_token_api_mode
from common.utils.xianyu_utils import trans_cookies
from app.api.deps import require_internal_auth
from app.utils.captcha_engine import normalize_captcha_engine

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_auth)],
)


class StartAccountRequest(BaseModel):
    """启动账号请求"""
    cookie_value: str | None = None  # 可选，不传则从数据库获取
    user_id: int | None = None


class SendMessageRequest(BaseModel):
    """发送消息请求"""
    chat_id: str
    message: str
    # 接收方（买家）用户ID；缺省时发送协议里的接收人会变成 None@goofish，买家收不到
    to_user_id: str | None = None
    # 是否等待服务端发送结果（识别 CSI_FORBID 等安全拦截）。默认 False 保持既有调用方零影响。
    wait_result: bool = False
    wait_timeout: float = 10.0


class ConfirmNoLogisticsRequest(BaseModel):
    account_id: str
    order_no: str
    item_id: str
    buyer_id: str = ""
    is_bargain: bool = False


class CancelOrderRequest(BaseModel):
    account_id: str
    order_no: str


class CreateChatRequest(BaseModel):
    """创建单聊会话请求
    
    通过 LWP 协议 /r/SingleChatConversation/create 创建或获取会话。
    服务端按 (pairFirst, pairSecond, bizType) 幂等生成 cid，已存在则直接返回现有 cid。
    """
    buyer_id: str  # 对方用户ID（买家ID），不带 @goofish 后缀
    item_id: str   # 关联商品ID


class LogRetentionRequest(BaseModel):
    """日志保留天数刷新请求"""
    retention_days: int


class SolveCaptchaRequest(BaseModel):
    """过滑块请求；可选携带续期上下文用于成功后持久化。"""
    account_id: str = ""          # 外部标识，仅用于日志与浏览器实例隔离
    account_row_id: int | None = None # xy_accounts.id，传入后成功时精准写回 Cookie
    url: str                      # punish 验证链接（punish?x5secdata=...）
    browser_timeout: int = 40     # 单次浏览器超时（秒）
    call_type: str = "remote"     # 调用类型：local-本机 / remote-远程
    call_user: str | None = None  # 调用用户（远程调用按秘钥查到的用户名）
    cookies: str = ""             # 可选：账号 Cookie（调用方开启"传递Cookie"开关时传入）。
                                  # 传入后链接过期时可凭此 Cookie 重取新链接继续处理。
    device_id: str = ""           # 可选：设备 ID，配合 cookies 重新请求 token 接口使用
    risk_log_id: int | None = None # backend-web 准入锁内预先创建的风控日志 ID
    token_cache_id: int | None = None # xy_token_cache.id，传入后可写入续期 Token
    token_user_id: str = ""       # Token 缓存用户 ID
    persist_token_cache: bool = False # 是否由 WebSocket 端完成 Token 缓存写入
    token_cache_write_mode: str = "renewal" # renewal-条件续期 / upsert-基础缓存新增或更新


@router.post("/logs/retention")
async def refresh_log_retention(request: LogRetentionRequest):
    """实时刷新日志保留天数"""
    try:
        from common.utils.logging_utils import update_log_retention

        updated = update_log_retention(request.retention_days)
        return {
            "success": True,
            "code": 200,
            "message": "日志保留天数已刷新" if updated else "日志保留天数无需变更",
            "data": {
                "retention_days": request.retention_days,
                "updated": updated,
            },
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"日志保留天数刷新失败: {str(e)}",
            "data": None,
        }


@router.post("/accounts/{account_id}/start")
async def start_account(account_id: str, request: StartAccountRequest = None):
    """
    启动账号任务
    
    Args:
        account_id: 账号ID
        request: 启动请求参数(可选)
        
    Returns:
        操作结果
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        from loguru import logger
        
        manager = get_manager()
        
        # 如果没有传递 cookie_value，从数据库获取
        cookie_value = None
        user_id = None
        if request:
            cookie_value = request.cookie_value
            user_id = request.user_id
        
        if not cookie_value:
            # 从数据库获取 cookie
            from common.db.session import async_session_maker
            from common.models import XYAccount
            from sqlalchemy import select
            
            async with async_session_maker() as session:
                result = await session.execute(
                    select(XYAccount).where(XYAccount.account_id == account_id)
                )
                account = result.scalars().first()
                if account:
                    cookie_value = account.cookie
                    user_id = account.owner_id
        
        if not cookie_value:
            return {
                "success": False,
                "code": 400,
                "message": f"账号 {account_id} 未找到有效的Cookie",
                "data": None,
            }
        
        # 更新内存中的数据
        manager.cookies[account_id] = cookie_value
        manager.cookie_status[account_id] = True
        manager.keywords.setdefault(account_id, [])
        
        # 直接调用异步方法启动任务
        await manager._add_cookie_async(account_id, cookie_value, user_id)
        
        logger.info(f"账号任务启动成功: {account_id}")
        
        return {
            "success": True,
            "code": 200,
            "message": "账号任务启动成功",
            "data": {
                "account_id": account_id,
                "status": "starting",
            },
        }
    except Exception as e:
        from loguru import logger
        import traceback
        logger.error(f"启动账号任务失败: {account_id}, 错误: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "code": 500,
            "message": f"启动账号任务失败: {str(e)}",
            "data": None,
        }


@router.post("/accounts/{account_id}/stop")
async def stop_account(account_id: str):
    """
    停止账号任务
    
    Args:
        account_id: 账号ID
        
    Returns:
        操作结果
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        from loguru import logger
        
        manager = get_manager()
        manager.remove_cookie(account_id)
        logger.info(f"账号任务停止成功: {account_id}")
        
        return {
            "success": True,
            "code": 200,
            "message": "账号任务停止成功",
            "data": {
                "account_id": account_id,
                "status": "stopped",
            },
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"停止账号任务失败: {str(e)}",
            "data": None,
        }


@router.post("/accounts/{account_id}/restart")
async def restart_account(account_id: str, request: StartAccountRequest = None):
    """
    重启账号任务
    
    Args:
        account_id: 账号ID
        request: 启动请求参数(可选，不传则从数据库获取Cookie)
        
    Returns:
        操作结果
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        from loguru import logger

        # 请求体可选：未携带时使用空请求，统一从数据库获取Cookie
        if request is None:
            request = StartAccountRequest()

        # 实际用于启动任务的 Cookie 与所属用户：
        # 优先用请求携带的值，未携带时回退数据库（避免重启时把空 Cookie 传给任务导致"未提供cookies"）
        cookie_str = request.cookie_value
        resolved_user_id = request.user_id

        # 重启前清除Token缓存，确保重新获取Token和完整Cookie
        # 注意：xy_token_cache.user_id 存的是闲鱼的 unb（myid），不是 cookie_id(account_id)
        # 因此必须先从 Cookie 中解析出 unb 再作为 user_id 参数删除
        try:
            from common.db.session import async_session_maker
            from common.utils.cookie_refresh import get_account_by_identity
            from common.utils.xianyu_utils import trans_cookies
            from sqlalchemy import text

            # 1) 请求未携带 Cookie 时，回退数据库查询（同时取账号归属用户）
            if not cookie_str:
                try:
                    account = await get_account_by_identity(
                        account_id,
                        owner_id=request.user_id,
                    )
                    if account:
                        cookie_str = account.cookie
                        if resolved_user_id is None:
                            resolved_user_id = account.owner_id
                except Exception as query_e:
                    logger.warning(f"查询账号Cookie失败: {query_e}")

            # 2) 解析 unb
            unb = ""
            if cookie_str:
                try:
                    cookies_dict = trans_cookies(cookie_str) or {}
                    unb = cookies_dict.get("unb", "") or ""
                except Exception as parse_e:
                    logger.warning(f"解析Cookie获取unb失败: {parse_e}")
                    unb = ""

            # 3) 用正确的 unb 作为唯一 user_id 删除 Token 缓存
            if unb:
                invalidation = await delete_token_cache(
                    token_user_id=unb,
                )
                logger.info(
                    f"账号重启前{invalidation.message}: "
                    f"account_id={account_id}, user_id={unb}"
                )
            else:
                logger.warning(f"未能解析出unb，跳过Token缓存清除: account_id={account_id}")
        except Exception as cache_e:
            logger.warning(f"清除Token缓存失败(不影响重启): {cache_e}")
        
        manager = get_manager()
        # 先停止
        manager.remove_cookie(account_id)
        # 再启动（使用解析后的 Cookie 与归属用户，避免空 Cookie 启动失败）
        manager.add_cookie(
            cookie_id=account_id,
            cookie_value=cookie_str,
            user_id=resolved_user_id
        )
        logger.info(f"账号任务重启成功: {account_id}")
        
        return {
            "success": True,
            "code": 200,
            "message": "账号任务重启成功",
            "data": {
                "account_id": account_id,
                "status": "restarting",
            },
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"重启账号任务失败: {str(e)}",
            "data": None,
        }


@router.post("/captcha/solve")
async def solve_captcha(request: SolveCaptchaRequest):
    """凭 punish 链接求解滑块，并按可选上下文持久化结果。

    默认模式不依赖账号是否运行，也不写账号或 Token 缓存；携带账号行 ID
    与 Token 缓存上下文时，成功后会写回 Cookie 并更新对应缓存。
    成功返回解出的 Cookie，失败直接返回 success=false（供外部系统使用）。
    远程调用会记录风控日志（call_type=remote，call_user=调用用户）。
    """
    import re
    import time as _time
    from loguru import logger

    url = (request.url or "").strip()
    if not url:
        return {"success": False, "code": 400, "message": "punish 链接不能为空", "data": None}

    # 清洗 account_id（外部传入，仅用于日志与浏览器实例目录隔离，防止路径注入）
    raw_id = (request.account_id or "external").strip()
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "", raw_id)[:64] or "external"
    timeout = max(20, min(int(request.browser_timeout or 40), 120))
    call_type = (request.call_type or "remote").strip() or "remote"
    call_user = (request.call_user or "").strip() or None
    existing_cookies_str = (request.cookies or "").strip()
    device_id = (request.device_id or "").strip()
    refetched_token_result: dict[str, object] = {}

    # 记录风控日志（处理中）
    log_id = request.risk_log_id if request.risk_log_id and request.risk_log_id > 0 else None
    start_ts = _time.time()

    def _create_processing_log() -> int | None:
        try:
            from common.db.compat import db_manager
            return db_manager.add_risk_control_log(
                # safe_id 仅用于日志展示和浏览器目录隔离；数据库查询必须使用
                # 原始账号标识，否则特殊字符账号会出现“写入与查询不一致”。
                cookie_id=raw_id,
                event_type="slider_captcha",
                event_description=f"触发场景: 远程过滑块接口, URL: {url}",
                processing_status="processing",
                call_type=call_type,
                call_user=call_user,
            )
        except Exception as log_e:
            logger.error(f"【过滑块接口】记录风控日志失败: {log_e}")
            return None

    if request.persist_token_cache and not log_id:
        async with get_account_risk_control_lock(raw_id):
            processing_check = await check_account_processing_risk_control_log(raw_id)
            if processing_check.has_processing:
                logger.warning(
                    f"【过滑块接口】account_id={safe_id} {processing_check.message}，"
                    "本次不重复处理"
                )
                return {
                    "success": False,
                    "code": 200,
                    "message": f"{processing_check.message}，本次不重复处理",
                    "data": {
                        "processing_conflict": True,
                        "processing_check_success": processing_check.success,
                    },
                }
            log_id = _create_processing_log()
        if not log_id:
            return {
                "success": False,
                "code": 200,
                "message": "创建风控处理日志失败，本次未启动滑块任务",
                "data": None,
            }
    if not log_id:
        log_id = _create_processing_log()

    def _update_log(
        status: str,
        result: str,
        engine: str | None = None,
        error: str | None = None,
    ) -> None:
        if not log_id:
            return
        try:
            from common.db.compat import db_manager as _dm
            kwargs = {"processing_status": status, "processing_result": result}
            if engine is not None:
                normalized_engine, error = normalize_captcha_engine(engine, error)
                kwargs["captcha_engine"] = normalized_engine
            if error is not None:
                kwargs["error_message"] = error
            _dm.update_risk_control_log(log_id=log_id, **kwargs)
        except Exception as ue:
            logger.error(f"【过滑块接口】更新风控日志失败: {ue}")

    def _merged_cookie_string(cookie_updates: dict[str, object] | None) -> str:
        try:
            merged = trans_cookies(existing_cookies_str)
        except Exception:
            merged = {}
        for name, value in (cookie_updates or {}).items():
            clean_name = str(name).strip()
            if clean_name:
                merged[clean_name] = "" if value is None else str(value)
        return "; ".join(f"{name}={value}" for name, value in merged.items())

    async def _persist_cookie_updates(
        cookie_updates: dict[str, object] | None,
        source: str,
    ) -> tuple[str, bool, str]:
        if not cookie_updates:
            return existing_cookies_str, True, "未返回新Cookie，无需写回"
        merged_cookies_str = _merged_cookie_string(cookie_updates)
        if not request.account_row_id or request.account_row_id <= 0:
            return merged_cookies_str, False, "未携带账号行ID，未写回Cookie"
        try:
            saved_cookies_str = await merge_account_cookie_fields(
                int(request.account_row_id),
                raw_id,
                cookie_updates,
            )
        except Exception as persist_error:
            message = (
                f"{source}返回Cookie合并写回异常："
                f"{type(persist_error).__name__}: {persist_error}"
            )
            logger.error(f"【过滑块接口】account_id={safe_id} {message}")
            return merged_cookies_str, False, message
        if saved_cookies_str:
            msg = f"{source}返回Cookie已写回数据库"
            logger.info(f"【过滑块接口】account_id={safe_id} {msg}")
            return saved_cookies_str, True, msg
        msg = f"{source}返回Cookie合并写回失败"
        logger.error(f"【过滑块接口】account_id={safe_id} {msg}")
        return merged_cookies_str, False, msg

    async def _persist_token_cache(
        token: object,
        merged_cookies_str: str,
        cookie_saved: bool,
    ) -> dict:
        nonlocal device_id
        if not request.persist_token_cache:
            return {}
        if not cookie_saved:
            return {"token_cache_saved": False, "token_cache_message": "Cookie未写回，跳过Token缓存写入"}
        token_user_id = (request.token_user_id or "").strip()
        write_mode = (request.token_cache_write_mode or "renewal").strip().lower()
        if not (token_user_id and device_id):
            return {"token_cache_saved": False, "token_cache_message": "缺少Token缓存写入上下文"}
        if write_mode == "renewal" and not request.token_cache_id:
            return {"token_cache_saved": False, "token_cache_message": "缺少续期Token缓存行ID"}
        if write_mode not in {"renewal", "upsert"}:
            return {
                "token_cache_saved": False,
                "token_cache_message": f"不支持的Token缓存写入模式：{write_mode}",
            }

        new_token = str(token or "").strip()
        token_response_cookies: dict[str, object] = {}
        token_response_cookie_saved = True

        def _token_cache_failure(message: str) -> dict:
            data = {
                "token_cache_saved": False,
                "token_cache_message": message,
                "token_response_cookie_saved": token_response_cookie_saved,
            }
            if token_response_cookies:
                data["token_response_cookies"] = dict(token_response_cookies)
            return data

        if not new_token:
            try:
                token_request_cookies = merged_cookies_str
                last_token_response: object = None
                # Token接口方式实时查库，与 WebSocket 主流程保持一致
                token_api_mode = await load_token_api_mode(safe_id)
                for token_attempt in range(2):
                    token_result = await request_im_token_with_fallback(
                        token_request_cookies,
                        device_id,
                        api_mode=token_api_mode,
                        log_tag=safe_id,
                    )
                    if token_result.device_id:
                        device_id = token_result.device_id
                    last_token_response = token_result.response_json
                    if token_result.response_cookies:
                        response_cookies = dict(token_result.response_cookies)
                        token_response_cookies.update(response_cookies)
                        (
                            token_request_cookies,
                            response_cookie_saved,
                            response_cookie_message,
                        ) = await _persist_cookie_updates(
                            response_cookies,
                            "滑块后Token接口",
                        )
                        if not response_cookie_saved:
                            token_response_cookie_saved = False
                            return _token_cache_failure(response_cookie_message)

                    new_token = extract_im_access_token(token_result.response_json) or ""
                    if new_token:
                        break
                    if token_attempt == 0 and token_result.response_cookies:
                        logger.info(
                            f"【过滑块接口】account_id={safe_id} Token接口下发新Cookie，"
                            "合并后重试一次"
                        )
                        continue

                    response_detail = str(
                        token_result.response_json.get("ret")
                        if isinstance(token_result.response_json, dict)
                        else last_token_response
                    )[:300]
                    return _token_cache_failure(
                        (
                            "滑块后重试Token接口仍未返回accessToken"
                            f"：{response_detail or '未返回错误说明'}"
                        )
                    )
                if not new_token:
                    return _token_cache_failure(
                        "滑块后重试Token接口仍未返回accessToken"
                    )
            except Exception as exc:
                return _token_cache_failure(
                    f"滑块后重试Token接口异常：{type(exc).__name__}: {exc}"
                )

        if write_mode == "upsert":
            cache_write = await upsert_token_cache(
                token_user_id=token_user_id,
                device_id=device_id,
                token=new_token,
            )
            data = {
                "token_cache_saved": cache_write.success,
                "token_cache_message": cache_write.message,
                "token_response_cookie_saved": token_response_cookie_saved,
            }
            if cache_write.expire_at:
                data["expire_at"] = cache_write.expire_at.isoformat()
            if token_response_cookies:
                data["token_response_cookies"] = token_response_cookies
            return data

        cache_write = await write_renewed_token_cache(
            cache_id=int(request.token_cache_id),
            token_user_id=token_user_id,
            device_id=device_id,
            token=new_token,
        )
        data = {
            "token_cache_saved": cache_write.success,
            "token_cache_message": cache_write.message,
            "token_response_cookie_saved": token_response_cookie_saved,
        }
        if cache_write.renew_expire_at:
            data["renew_expire_at"] = cache_write.renew_expire_at.isoformat()
        if token_response_cookies:
            data["token_response_cookies"] = token_response_cookies
        return data

    def _log_token_cache_result(result_data: dict) -> None:
        """记录异步持久化结果，调用方超时后仍可定位具体原因。"""
        if not request.persist_token_cache:
            return
        message = str(result_data.get("token_cache_message") or "Token缓存写入结果未知")
        if result_data.get("token_cache_saved"):
            logger.info(f"【过滑块接口】account_id={safe_id} {message}")
        else:
            logger.error(f"【过滑块接口】account_id={safe_id} {message}")

    try:
        from app.services.captcha.slider_stealth import run_slider_verification_with_fallback

        # 若调用方传入了账号 Cookie（开启了"传递Cookie"开关）：
        #   - 把 Cookie 作为 existing_cookies_str 提供给兜底引擎注入；
        #   - 构造 url_provider，遇到"抱歉，页面访问出现了问题"（链接过期）时凭 Cookie 重取新链接，
        #     与本机处理滑块的逻辑保持一致。
        # 未传 Cookie 时保持原模式B：链接过期或失败直接判失败（cookies="" / url_provider=None）。
        url_provider = None
        if existing_cookies_str:
            from common.services.captcha.token_refetch import request_fresh_captcha_url
            from app.services.captcha.slider_stealth import CAPTCHA_NOT_REQUIRED
            from common.utils.xianyu_utils import trans_cookies

            try:
                _cookies_dict = trans_cookies(existing_cookies_str)
            except Exception:
                _cookies_dict = {}
            refetch_cookies_state = [existing_cookies_str]

            def _remote_url_provider():
                """凭传入的 Cookie 重新请求 token 接口，拿到新鲜验证链接（远程端链接过期兜底）。"""
                res = request_fresh_captcha_url(
                    safe_id,
                    _cookies_dict,
                    refetch_cookies_state[0],
                    device_id,
                )
                accumulated_cookies = dict(
                    refetched_token_result.get("new_cookies") or {}
                )
                refetched_token_result.clear()
                refetched_token_result.update(res)
                response_cookies = res.get("new_cookies")
                if isinstance(response_cookies, dict) and response_cookies:
                    accumulated_cookies.update(response_cookies)
                    _cookies_dict.update(response_cookies)
                    refetch_cookies_state[0] = "; ".join(
                        f"{name}={value}" for name, value in _cookies_dict.items()
                    )
                refetched_token_result["new_cookies"] = accumulated_cookies
                if res.get("token_ok"):
                    # 风控已解除、无需滑块：返回哨兵，让上层提前结束滑块流程
                    return CAPTCHA_NOT_REQUIRED
                return res.get("fresh_url")

            url_provider = _remote_url_provider
            logger.info(f"【过滑块接口】account_id={safe_id} 已携带 Cookie，启用链接过期自动重取")

        # 被调用接口不信任请求体中的 call_type，所有请求固定进入远程桶，避免伪装成本地权重。
        # 远程内部默认无 Cookie 优先；任一队首等待满70秒后按最早入队优先。
        weight_class = "remote_cookie" if existing_cookies_str else "remote"
        slider_args = (
            safe_id, url, True, False, timeout, existing_cookies_str, url_provider,
        )
        selected_slider_mode = await refresh_slider_mode_from_database()
        if selected_slider_mode == SLIDER_MODE_REAL_MOUSE:
            # 被调用方请求在线程池之前参与本地/远程实时加权排队。
            success, cookies, engine = await real_mouse_weighted_runner.submit(
                weight_class,
                run_slider_verification_with_fallback,
                *slider_args,
                weight_class=weight_class,
                slider_mode=selected_slider_mode,
            )
        else:
            success, cookies, engine = await run_browser_task(
                run_slider_verification_with_fallback,
                *slider_args,
                weight_class=weight_class,
                slider_mode=selected_slider_mode,
            )
    except asyncio.CancelledError:
        cancelled_cookies = refetched_token_result.get("new_cookies")
        if isinstance(cancelled_cookies, dict) and cancelled_cookies:
            await _persist_cookie_updates(cancelled_cookies, "重取Token")
        logger.warning(f"【过滑块接口】account_id={safe_id} 执行任务被取消")
        raise
    except Exception as e:
        logger.error(f"【过滑块接口】account_id={safe_id} 执行异常: {e}")
        exception_cookie_data: dict[str, object] = {}
        exception_cookies = refetched_token_result.get("new_cookies")
        if isinstance(exception_cookies, dict) and exception_cookies:
            _, exception_cookie_saved, exception_cookie_message = (
                await _persist_cookie_updates(exception_cookies, "重取Token")
            )
            exception_cookie_data = {
                "cookies": exception_cookies,
                "cookie_saved": exception_cookie_saved,
                "cookie_message": exception_cookie_message,
            }
        _update_log(
            "error",
            f"过滑块执行异常，耗时: {_time.time() - start_ts:.2f}秒",
            error=str(e),
        )
        return {
            "success": False,
            "code": 500,
            "message": f"过滑块执行异常: {str(e)}",
            "data": exception_cookie_data or None,
            "_risk_log_id": log_id,
        }

    duration = _time.time() - start_ts
    refetched_cookies = refetched_token_result.get("new_cookies")
    if not isinstance(refetched_cookies, dict):
        refetched_cookies = {}

    if success and not cookies and refetched_token_result.get("token_ok"):
        refetched_device_id = str(refetched_token_result.get("device_id") or "").strip()
        if refetched_device_id:
            device_id = refetched_device_id
        merged_cookies_str, cookie_saved, cookie_message = await _persist_cookie_updates(
            refetched_cookies,
            "重取Token",
        )
        token_cache_data = await _persist_token_cache(
            refetched_token_result.get("new_token"),
            merged_cookies_str,
            cookie_saved,
        )
        _log_token_cache_result(token_cache_data)
        token_response_cookies = token_cache_data.pop("token_response_cookies", {})
        token_response_cookie_saved = bool(
            token_cache_data.pop("token_response_cookie_saved", True)
        )
        cookie_saved = cookie_saved and token_response_cookie_saved
        if not token_response_cookie_saved:
            cookie_message = f"{cookie_message}；滑块后Token接口Cookie合并写回失败"
        returned_cookies = {**refetched_cookies, **token_response_cookies}
        _update_log(
            "success",
            f"重取验证链接时Token已可用，无需滑块，耗时: {duration:.2f}秒",
            engine=engine,
        )
        return {
            "success": True,
            "code": 200,
            "message": "Token已可用，无需滑块",
            "data": {
                "engine": engine,
                "cookies": returned_cookies,
                "token_already_available": True,
                "url_expired": False,
                "cookie_saved": cookie_saved,
                "cookie_message": cookie_message,
                **token_cache_data,
            },
            "_risk_log_id": log_id,
        }
    if success and cookies:
        # 浏览器 Cookie 与重取链接时 Token 接口下发的 Cookie 一次性合并写回，
        # 防止 fresh_url 分支丢失新 _m_h5_tk。
        # 浏览器可能返回注入时的全量旧 Cookie，重取 Token 接口
        # 下发的是已知最新增量，同名字段必须以重取结果为准。
        combined_cookies = dict(cookies)
        combined_cookies.update(refetched_cookies)
        merged_cookies_str, cookie_saved, cookie_message = await _persist_cookie_updates(
            combined_cookies,
            "过滑块",
        )
        token_cache_data = await _persist_token_cache(
            None,
            merged_cookies_str,
            cookie_saved,
        )
        _log_token_cache_result(token_cache_data)
        token_response_cookies = token_cache_data.pop("token_response_cookies", {})
        token_response_cookie_saved = bool(
            token_cache_data.pop("token_response_cookie_saved", True)
        )
        cookie_saved = cookie_saved and token_response_cookie_saved
        if not token_response_cookie_saved:
            cookie_message = f"{cookie_message}；滑块后Token接口Cookie合并写回失败"
        returned_cookies = {**combined_cookies, **token_response_cookies}
        _update_log(
            "success",
            f"远程过滑块成功，耗时: {duration:.2f}秒",
            engine=engine,
        )
        return {
            "success": True, "code": 200, "message": "过滑块成功",
            "data": {
                "engine": engine,
                "cookies": returned_cookies,
                "url_expired": False,
                "cookie_saved": cookie_saved,
                "cookie_message": cookie_message,
                **token_cache_data,
            },
            "_risk_log_id": log_id,
        }
    # 即使滑块最终失败，重取验证链接阶段下发的 Cookie 也必须写回，避免下一轮
    # 继续使用已经过期的 _m_h5_tk。
    failure_cookie_data: dict[str, object] = {}
    if refetched_cookies:
        _, refetch_cookie_saved, refetch_cookie_message = await _persist_cookie_updates(
            refetched_cookies,
            "重取Token",
        )
        failure_cookie_data = {
            "cookies": refetched_cookies,
            "cookie_saved": refetch_cookie_saved,
            "cookie_message": refetch_cookie_message,
        }

    # 验证链接已过期：明确告知调用方刷新URL后重试（区别于普通过滑块失败）
    # 注意：url_expired 不是"通过引擎"，不写入 captcha_engine 字段（避免污染引擎枚举/前端展示），
    # 过期信息体现在 processing_result 文案与返回体 data 中即可。
    if engine == "url_expired":
        _update_log(
            "failed",
            f"远程过滑块失败(验证链接已过期)，耗时: {duration:.2f}秒",
        )
        return {
            "success": False, "code": 200, "message": "验证链接已过期，请刷新URL后重试",
            "data": {
                "engine": engine,
                "url_expired": True,
                **failure_cookie_data,
            },
            "_risk_log_id": log_id,
        }
    _update_log(
        "failed",
        f"远程过滑块失败，耗时: {duration:.2f}秒",
        engine=engine,
    )
    return {
        "success": False,
        "code": 200,
        "message": "过滑块失败",
        "data": {
            "engine": engine,
            "url_expired": False,
            **failure_cookie_data,
        },
        "_risk_log_id": log_id,
    }


@router.get("/accounts/connection-stats")
async def get_connection_stats():
    """统计真实 WebSocket 连接状态（已连接账号数量等）"""
    try:
        from app.services.xianyu.cookie_manager import get_manager

        manager = get_manager()
        stats = manager.get_connection_stats()

        return {
            "success": True,
            "code": 200,
            "message": "查询成功",
            "data": stats,
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"查询连接统计失败: {str(e)}",
            "data": None,
        }


@router.get("/accounts/{account_id}/status")
async def get_account_status(account_id: str):
    """
    查询账号任务状态

    Args:
        account_id: 账号ID
        
    Returns:
        任务状态信息
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        
        manager = get_manager()
        status = manager.get_task_status(account_id)
        
        return {
            "success": True,
            "code": 200,
            "message": "查询成功",
            "data": {
                "account_id": account_id,
                **status
            },
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"查询账号状态失败: {str(e)}",
            "data": None,
        }


@router.post("/accounts/{account_id}/send-message")
async def send_message(account_id: str, request: SendMessageRequest):
    """
    发送消息
    
    Args:
        account_id: 账号ID
        request: 消息请求参数
        
    Returns:
        操作结果
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        from loguru import logger
        
        manager = get_manager()
        
        # 获取账号实例
        instance = manager.instances.get(account_id)
        if not instance:
            return {
                "success": False,
                "code": 404,
                "message": f"账号 {account_id} 未运行或不存在",
                "data": None,
            }
        
        # 检查是否有 WebSocket 连接
        if not hasattr(instance, 'ws') or not instance.ws:
            return {
                "success": False,
                "code": 400,
                "message": f"账号 {account_id} WebSocket 未连接",
                "data": None,
            }
        
        if not request.to_user_id:
            return {
                "success": False,
                "code": 400,
                "message": "缺少接收方用户ID(to_user_id)",
                "data": None,
            }

        # 发送消息
        send_result = await instance.send_msg(
            websocket=instance.ws,
            chat_id=request.chat_id,
            send_user_id=request.to_user_id,
            content=request.message,
        )

        # WebSocket 发送层失败：直接判失败
        if not isinstance(send_result, dict) or not send_result.get("success"):
            err = send_result.get("error_message") if isinstance(send_result, dict) else None
            return {
                "success": False,
                "code": 500,
                "message": f"消息发送失败: {err or '未知错误'}",
                "data": {"send_status": "failed", "send_fail_reason": err},
            }

        # 可选：等待服务端响应，识别是否被安全拦截（CSI_FORBID 等）
        send_status = "unknown"
        send_fail_reason = None
        if request.wait_result:
            try:
                reason = await instance.wait_send_reject_reason(
                    send_result.get("send_future"),
                    send_result.get("mid"),
                    request.wait_timeout,
                )
                if reason:
                    send_status = "failed"
                    send_fail_reason = reason
                else:
                    send_status = "success"
            except Exception as wait_e:  # noqa: BLE001
                logger.warning(f"【{account_id}】等待发送结果异常: {wait_e}")

        logger.info(f"【{account_id}】消息发送成功: chat_id={request.chat_id}, send_status={send_status}")

        return {
            "success": True,
            "code": 200,
            "message": "消息发送成功",
            "data": {
                "account_id": account_id,
                "chat_id": request.chat_id,
                "message": request.message,
                "send_status": send_status,
                "send_fail_reason": send_fail_reason,
            },
        }
    except Exception as e:
        return {
            "success": False,
            "code": 500,
            "message": f"发送消息失败: {str(e)}",
            "data": None,
        }


@router.post("/orders/confirm-no-logistics")
async def confirm_no_logistics(request: ConfirmNoLogisticsRequest):
    """无物流发货：仅在闲鱼确认发货（不发送任何聊天内容）"""
    from app.services.xianyu.cookie_manager import get_manager
    from common.db.session import async_session_maker
    from common.services.order_service import OrderService

    xianyu_live = get_manager().instances.get(request.account_id)
    if not xianyu_live:
        return {"success": False, "code": 404, "message": "账号未连接", "data": None}

    # 无物流发货同样属于实际发货入口，金额为0时先刷新订单详情，避免绕过金额保护。
    amount_ok = await xianyu_live.order_actions._ensure_order_amount_before_delivery(
        order_id=request.order_no,
        item_id=request.item_id,
        buyer_id=request.buyer_id,
    )
    if not amount_ok:
        return {
            "success": False,
            "code": 400,
            "message": "订单金额为0，发货前刷新订单详情失败，请稍后重试",
            "data": None,
        }

    if request.is_bargain:
        result = await xianyu_live.order_actions.auto_freeshipping(
            request.order_no, request.item_id, request.buyer_id
        )
    else:
        result = await xianyu_live.order_actions.auto_confirm(
            request.order_no, request.item_id
        )

    if not result or not result.get("success"):
        message = (result or {}).get("error") or (result or {}).get("message") or "无物流发货失败"
        return {"success": False, "code": 400, "message": message, "data": result}

    async with async_session_maker() as session:
        await OrderService(session).update_order_delivery_info(
            request.order_no,
            status="shipped",
            delivery_method="manual",
            delivery_content="无物流发货",
        )

    return {"success": True, "code": 200, "message": "无物流发货成功", "data": result}


@router.post("/orders/cancel")
async def cancel_order(request: CancelOrderRequest):
    """卖家关闭（取消）订单"""
    from app.services.xianyu.cookie_manager import get_manager
    from common.db.session import async_session_maker
    from common.models import XYOrder
    from sqlalchemy import update

    xianyu_live = get_manager().instances.get(request.account_id)
    if not xianyu_live:
        return {"success": False, "code": 404, "message": "账号未连接", "data": None}

    closed = await xianyu_live.order_actions.close_order_by_seller(request.order_no)
    if not closed:
        return {"success": False, "code": 400, "message": "取消订单失败，请检查闲鱼订单状态", "data": None}

    async with async_session_maker() as session:
        await session.execute(
            update(XYOrder).where(XYOrder.order_no == request.order_no).values(status="cancelled")
        )
        await session.commit()
    return {"success": True, "code": 200, "message": "订单已取消", "data": {"order_no": request.order_no}}


@router.post("/accounts/{account_id}/refresh-token")
async def refresh_token(account_id: str):
    """
    刷新账号Token
    
    Args:
        account_id: 账号ID
        
    Returns:
        刷新结果
    """
    from loguru import logger
    from app.services.xianyu.xianyu_async import XianyuAsync
    
    logger.info(f"【内部API】收到Token刷新请求: account_id={account_id}")
    
    # 获取 XianyuAsync 实例
    instance = XianyuAsync.get_instance(account_id)
    
    if not instance:
        raise HTTPException(
            status_code=404,
            detail=f"账号 {account_id} 未启动或不存在"
        )
    
    # 触发 Token 刷新
    try:
        if instance.token_manager:
            # 使用 token_manager 触发刷新
            await instance.token_manager.trigger_refresh()
            logger.info(f"【内部API】Token刷新请求已提交: account_id={account_id}")
            
            return {
                "success": True,
                "code": 200,
                "message": "Token刷新请求已提交",
                "data": {
                    "account_id": account_id
                }
            }
        else:
            raise HTTPException(
                status_code=500,
                detail="Token管理器未初始化"
            )
    except Exception as e:
        logger.error(f"【内部API】Token刷新失败: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Token刷新失败: {str(e)}"
        )


class PasswordLoginRefreshRequest(BaseModel):
    """密码登录刷新请求"""
    trigger_reason: str = "账号已掉线"  # 触发原因


@router.post("/accounts/{account_id}/password-login-refresh")
async def password_login_refresh(account_id: str, request: PasswordLoginRefreshRequest = None):
    """
    触发账号密码登录刷新Cookie（异步，立即返回）
    
    当检测到Session过期时，定时任务可以调用此接口触发密码登录刷新Cookie。
    此接口会在后台启动密码登录任务，立即返回，不等待登录完成。
    
    Args:
        account_id: 账号ID
        request: 请求参数（可选）
        
    Returns:
        操作结果（任务已启动）
    """
    import asyncio
    from loguru import logger
    from app.services.captcha.password_login_state import password_login_state
    
    trigger_reason = request.trigger_reason if request else "账号已掉线"
    logger.info(f"【内部API】收到密码登录刷新请求: account_id={account_id}, 原因={trigger_reason}")
    
    # 检查账号是否正在处理中，防止重复触发
    if not password_login_state.start_processing(account_id):
        # 账号正在处理中，直接返回成功（丢弃请求，不报错）
        logger.info(f"【内部API】账号 {account_id} 正在处理密码登录，丢弃本次请求")
        return {
            "success": True,
            "code": 200,
            "message": "账号正在处理中，本次请求已丢弃",
            "data": {"account_id": account_id, "status": "already_processing"}
        }
    
    # 在后台启动密码登录任务，不等待结果
    asyncio.create_task(_execute_password_login_refresh(account_id, trigger_reason))
    
    logger.info(f"【内部API】密码登录任务已启动: account_id={account_id}")
    return {
        "success": True,
        "code": 200,
        "message": "密码登录任务已启动",
        "data": {"account_id": account_id, "status": "started"}
    }


async def _execute_password_login_refresh(account_id: str, trigger_reason: str):
    """
    后台执行密码登录刷新（异步任务）
    
    Args:
        account_id: 账号ID
        trigger_reason: 触发原因
    """
    from loguru import logger
    from app.services.xianyu.cookie_manager import get_manager
    from app.services.captcha.password_login_state import password_login_state
    
    try:
        # 获取 CookieManager 实例
        manager = get_manager()
        xianyu_live = manager.instances.get(account_id)
        
        if not xianyu_live:
            # 实例不存在，尝试直接执行密码登录（不依赖运行中的实例）
            logger.warning(f"【内部API】账号 {account_id} 实例未运行，尝试独立执行密码登录")
            await _standalone_password_login(account_id, trigger_reason)
            return
        
        # 调用 cookie_token_manager 的密码登录刷新方法
        if hasattr(xianyu_live, 'cookie_token_manager') and xianyu_live.cookie_token_manager:
            refresh_result = await xianyu_live.cookie_token_manager.try_password_login_refresh(trigger_reason)
            
            if refresh_result == "no_credentials":
                logger.warning(f"【内部API】账号 {account_id} 未配置用户名或密码")
            elif refresh_result == True:
                logger.info(f"【内部API】账号 {account_id} 密码登录刷新成功")
            else:
                logger.warning(f"【内部API】账号 {account_id} 密码登录刷新失败")
        else:
            # CookieTokenManager 未初始化，回退到独立执行密码登录
            logger.warning(f"【内部API】账号 {account_id} 的 CookieTokenManager 未初始化，尝试独立执行密码登录")
            await _standalone_password_login(account_id, trigger_reason)
            
    except Exception as e:
        logger.error(f"【内部API】密码登录刷新异常: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # 清理密码登录处理状态
        password_login_state.finish_processing(account_id)


async def _standalone_password_login(account_id: str, trigger_reason: str) -> dict:
    """
    独立执行密码登录（不依赖运行中的实例）
    
    当 WebSocket 实例未运行时，直接从数据库获取账号信息并执行密码登录。
    
    Args:
        account_id: 账号ID
        trigger_reason: 触发原因
        
    Returns:
        操作结果字典
    """
    import asyncio
    import time as _time
    from loguru import logger
    from common.db.compat import db_manager
    
    logger.info(f"【内部API】开始独立执行密码登录: account_id={account_id}")
    
    # 记录账号登录日志的辅助函数
    start_ts = _time.time()
    login_username: str | None = None
    # 接口续期失败原因（在接口续期失败后赋值，供后续日志拼接）
    _api_renew_fail_msg: str = ""

    def _record_login_log(
        login_status: str,
        failure_reason: str | None = None,
        error_message: str | None = None,
        updated_cookie_names: str | None = None,
    ) -> None:
        """记录一条账号登录日志（写日志失败不影响主流程）。"""
        try:
            duration_ms = int((_time.time() - start_ts) * 1000)
            # 如果接口续期失败了，在 error_message 前拼接续期失败信息
            final_error_message = error_message
            if _api_renew_fail_msg and error_message:
                final_error_message = f"{_api_renew_fail_msg}，{error_message}"
            db_manager.add_account_login_log(
                cookie_id=account_id,
                login_status=login_status,
                username=login_username,
                trigger_reason=trigger_reason,
                failure_reason=failure_reason,
                error_message=final_error_message,
                updated_cookie_names=updated_cookie_names,
                duration_ms=duration_ms,
            )
        except Exception as log_e:
            logger.warning(f"【内部API】写入账号登录日志失败: {log_e}")

    try:
        # 从数据库获取账号信息
        account_info = await asyncio.to_thread(db_manager.get_cookie_details, account_id)
        
        if not account_info:
            logger.error(f"【内部API】无法获取账号信息: {account_id}")
            _record_login_log("failed", "account_info_missing", "账号不存在")
            return {
                "success": False,
                "code": 404,
                "message": "账号不存在",
                "data": {"account_id": account_id}
            }
        
        login_username = (account_info.get('username') or '') or None

        # ====== 优先尝试接口续期（轻量级，无需浏览器和密码） ======
        cookies_str = account_info.get('cookie_value', '')
        if cookies_str and cookies_str.strip():
            try:
                from common.services.cookie_renew_api_service import cookie_renew_api_service
                logger.info(f"【内部API】账号 {account_id} 先尝试接口续期...")
                # 记录续期前的全量cookies
                logger.info(f"【{account_id}】[续期前全量Cookies] {cookies_str}")
                renew_result = await cookie_renew_api_service.renew(cookies_str, account_id)

                # 不管续期是否成功，有Cookie更新就先写库
                if renew_result.updated_cookie_names:
                    db_manager.update_cookie_account_info(
                        account_id,
                        cookie_value=renew_result.new_cookies_str
                    )
                    logger.info(
                        f"【内部API】账号 {account_id} 接口返回Cookie已更新 "
                        f"{len(renew_result.updated_cookie_names)} 个字段"
                    )

                # 记录续期后的全量cookies（不管成功失败都打印）
                logger.info(f"【{account_id}】[续期后全量Cookies] {renew_result.new_cookies_str or cookies_str}")

                if renew_result.success:
                    renew_method_desc = "接口续期" if renew_result.renew_method == "api" else "浏览器续期"
                    logger.info(f"【内部API】账号 {account_id} {renew_method_desc}成功，跳过密码登录")
                    log_reason = "api_renew_success" if renew_result.renew_method == "api" else "browser_renew_success"
                    _record_login_log(
                        "success",
                        log_reason,
                        f"{renew_method_desc}成功，更新了 {len(renew_result.updated_cookie_names)} 个字段，无需密码登录",
                        updated_cookie_names=",".join(renew_result.updated_cookie_names) if renew_result.updated_cookie_names else None,
                    )
                    return {
                        "success": True,
                        "code": 200,
                        "message": f"{renew_method_desc}成功，更新了 {len(renew_result.updated_cookie_names)} 个字段，无需密码登录",
                        "data": {"account_id": account_id, "method": log_reason}
                    }
                else:
                    logger.info(
                        f"【内部API】账号 {account_id} 续期未成功"
                        f"（{renew_result.api_message}），继续尝试密码登录..."
                    )
            except Exception as renew_exc:
                logger.warning(f"【内部API】账号 {account_id} 续期异常（不影响密码登录）: {renew_exc}")

        # ====== 续期未成功，继续密码登录流程 ======
        _api_renew_fail_msg = "接口续期和浏览器续期均失败"
        username = account_info.get('username', '')
        password = account_info.get('password', '')
        show_browser = account_info.get('show_browser', False)
        
        if not username or not password:
            err_msg = f"{_api_renew_fail_msg}，且未配置用户名或密码，账号已自动禁用"
            logger.warning(f"【内部API】账号 {account_id} 未配置用户名或密码")
            # 自动禁用账号
            try:
                db_manager.disable_account(account_id, reason=f"{trigger_reason}且未配置密码，自动禁用")
                logger.warning(f"【内部API】账号 {account_id} 已自动禁用")
            except Exception as disable_e:
                logger.error(f"【内部API】自动禁用账号失败: {disable_e}")
            
            _record_login_log("no_credentials", "no_credentials", err_msg)
            return {
                "success": False,
                "code": 400,
                "message": "未配置用户名或密码，账号已自动禁用",
                "data": {"account_id": account_id, "reason": "no_credentials"}
            }
        
        # 使用 Playwright 执行密码登录
        from app.services.captcha.xianyu_slider_stealth import XianyuSliderStealth
        
        browser_mode = "有头" if show_browser else "无头"
        logger.info(f"【内部API】使用{browser_mode}浏览器进行密码登录: {username}")
        
        def _do_login():
            slider = XianyuSliderStealth(
                user_id=account_id,
                enable_learning=False,
                headless=not show_browser
            )
            try:
                return slider.login_with_password_playwright(
                    account=username,
                    password=password,
                    show_browser=show_browser
                )
            finally:
                try:
                    slider.close()
                except Exception:
                    pass
        
        # 密码登录驱动浏览器，走浏览器任务专用线程池，避免占用默认线程池拖垮 aiohttp
        from app.services.captcha.concurrency import run_browser_task
        result = await run_browser_task(_do_login)
        
        if result:
            # 登录成功，更新数据库中的Cookie
            new_cookies_str = '; '.join([f"{k}={v}" for k, v in result.items()])
            # 记录密码登录获取到的新cookies
            logger.info(f"【{account_id}】[密码登录获取的新Cookies] {new_cookies_str}")
            
            success = db_manager.update_cookie_account_info(
                account_id,
                cookie_value=new_cookies_str
            )
            
            if success:
                logger.info(f"【内部API】账号 {account_id} 密码登录成功，Cookie已更新到数据库")
                
                # 清除Token缓存
                try:
                    from common.db.session import async_session_maker
                    from sqlalchemy import text
                    unb = result.get('unb', '')
                    if unb:
                        invalidation = await mark_token_cache_expired(
                            token_user_id=unb,
                            invalidate_valid_cache=True,
                        )
                        logger.info(
                            f"【内部API】{invalidation.message}: user_id={unb}"
                        )
                except Exception as cache_e:
                    logger.warning(f"【内部API】清除Token缓存失败: {cache_e}")
                
                _record_login_log("success", None, "密码登录成功，Cookie已更新")
                return {
                    "success": True,
                    "code": 200,
                    "message": "密码登录成功，Cookie已更新",
                    "data": {"account_id": account_id, "cookie_count": len(result)}
                }
            else:
                logger.error(f"【内部API】账号 {account_id} 登录成功但更新数据库失败")
                _record_login_log("failed", "cookie_update_failed", "密码登录成功但更新数据库失败")
                return {
                    "success": False,
                    "code": 500,
                    "message": "登录成功但更新数据库失败",
                    "data": {"account_id": account_id}
                }
        else:
            logger.warning(f"【内部API】账号 {account_id} 密码登录失败")
            _record_login_log("failed", "login_no_cookie_returned", "密码登录失败，未获取到Cookie")
            return {
                "success": False,
                "code": 500,
                "message": "密码登录失败，未获取到Cookie",
                "data": {"account_id": account_id}
            }
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"【内部API】独立密码登录异常: {error_msg}")
        
        # ============== baxia-punish 风控图形滑块特殊处理 ==============
        try:
            from common.services.captcha.xianyu_slider_stealth import BaxiaPunishCaptchaException
            _is_baxia_punish = isinstance(e, BaxiaPunishCaptchaException)
        except Exception:
            _is_baxia_punish = False
        
        if _is_baxia_punish:
            logger.warning(
                f"【内部API】账号 {account_id} 触发风控图形滑块验证，账号本身正常，"
                f"仅设置 5 小时冷却（不禁用账号）：{error_msg}"
            )
            try:
                from common.utils.cookie_refresh import _password_error_cooldown
                import time as _time2
                _password_error_cooldown[account_id] = _time2.time()
            except Exception as cooldown_e:
                logger.warning(f"【内部API】写入风控冷却失败: {cooldown_e}")
            _record_login_log("failed", "baxia_punish_captcha", error_msg)
            return {
                "success": False,
                "code": 429,
                "message": (
                    f"触发闲鱼风控图形验证（如\"找两个松鼠\"），账号正常但暂时无法自动登录，"
                    f"已暂停 5 小时。请稍后重试或手动登录。"
                ),
                "data": {
                    "account_id": account_id,
                    "reason": "baxia_punish_captcha",
                    "cooldown_hours": 5,
                }
            }
        # ============== baxia-punish 处理结束 ==============
        
        # 检测账密错误，禁用账号
        is_bad_credentials = (
            '账密错误' in error_msg
            or '账号密码错误' in error_msg
            or '用户名或密码错误' in error_msg
        )
        if is_bad_credentials:
            disable_reason = error_msg if error_msg else "账号密码错误"
            try:
                db_manager.disable_account(account_id, reason=disable_reason)
                logger.warning(f"【内部API】检测到账密错误，账号 {account_id} 已自动禁用，原因: {disable_reason}")
            except Exception as disable_e:
                logger.error(f"【内部API】禁用账号失败: {disable_e}")
        
        _record_login_log(
            "failed",
            "bad_credentials" if is_bad_credentials else "exception",
            error_msg,
        )
        return {
            "success": False,
            "code": 500,
            "message": f"密码登录异常: {error_msg}",
            "data": {"account_id": account_id}
        }


@router.post("/accounts/{account_id}/create-chat")
async def create_chat(account_id: str, request: CreateChatRequest):
    """
    创建（或获取）单聊会话接口
    
    通过账号的活跃 WebSocket 连接向闲鱼发送 LWP 消息，
    等待服务端响应并返回会话ID（chat_id）。
    
    服务端按 (pairFirst, pairSecond, bizType) 幂等生成 cid，
    已存在的会话会直接返回现有 cid，不会重复创建。
    
    场景：订单手动发货时，如果订单缺少 chat_id，需要先创建会话再发货。
    
    Args:
        account_id: 账号ID
        request: 请求参数（买家ID、商品ID）
    
    Returns:
        操作结果，data.chat_id 为会话ID
    """
    try:
        from app.services.xianyu.cookie_manager import get_manager
        from loguru import logger
        
        logger.info(
            f"【内部API】收到创建会话请求: account_id={account_id}, "
            f"buyer_id={request.buyer_id}, item_id={request.item_id}"
        )
        
        if not request.buyer_id:
            return {
                "success": False,
                "code": 400,
                "message": "买家ID不能为空",
                "data": None
            }
        if not request.item_id:
            return {
                "success": False,
                "code": 400,
                "message": "商品ID不能为空",
                "data": None
            }
        
        # 获取 XianyuAsync 实例
        manager = get_manager()
        xianyu_live = manager.instances.get(account_id)
        
        if not xianyu_live:
            return {
                "success": False,
                "code": 404,
                "message": f"账号 {account_id} 未启动或不存在，请先启动账号",
                "data": None
            }
        
        # 检查 WebSocket 连接状态
        ws = xianyu_live.connection_manager.ws if xianyu_live.connection_manager else None
        if ws is None:
            return {
                "success": False,
                "code": 503,
                "message": f"账号 {account_id} 的 WebSocket 未连接，请等待连接建立或重启账号",
                "data": None
            }
        
        # 调用创建会话
        try:
            chat_id = await xianyu_live.create_chat_conversation(
                to_user_id=request.buyer_id,
                item_id=request.item_id,
            )
        except ConnectionError as ce:
            return {
                "success": False,
                "code": 503,
                "message": str(ce),
                "data": None
            }
        except TimeoutError as te:
            return {
                "success": False,
                "code": 504,
                "message": str(te),
                "data": None
            }
        except ValueError as ve:
            return {
                "success": False,
                "code": 500,
                "message": f"创建会话响应异常: {ve}",
                "data": None
            }
        
        logger.info(
            f"【内部API】创建会话成功: account_id={account_id}, "
            f"buyer_id={request.buyer_id}, chat_id={chat_id}"
        )
        return {
            "success": True,
            "code": 200,
            "message": "创建会话成功",
            "data": {
                "account_id": account_id,
                "buyer_id": request.buyer_id,
                "item_id": request.item_id,
                "chat_id": chat_id,
            }
        }
    except Exception as e:
        from loguru import logger
        import traceback
        logger.error(f"【内部API】创建会话异常: {e}")
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "code": 500,
            "message": f"创建会话异常: {str(e)}",
            "data": None
        }


@router.post("/system/self-restart")
async def system_self_restart():
    """
    重启本服务（消息服务 / websocket）

    由 backend-web 的系统管理接口调用。自动识别运行环境：
    - docker：本进程延迟自杀退出，容器 restart 策略自动拉起
    - dev/frozen：派生脱离父进程的协调子进程，杀端口后重新拉起

    先返回成功响应，再在后台触发重启。
    """
    from common.utils.service_restart import restart_service

    result = restart_service("websocket")
    return {
        "success": bool(result.get("success")),
        "code": 200 if result.get("success") else 500,
        "message": result.get("message") or "",
        "data": {"mode": result.get("mode")},
    }
