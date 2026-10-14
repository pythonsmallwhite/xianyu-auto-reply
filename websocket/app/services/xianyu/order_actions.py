"""
订单手动操作模块（无物流确认发货、免拼发货、卖家关闭订单）

从原自动发货模块中保留下来的平台订单操作，供后台「无物流发货」「取消订单」使用。
卡券发货、自动发货及其相关模式已删除。
"""

import asyncio
import json
import time
import aiohttp
from decimal import Decimal, InvalidOperation
from loguru import logger

from common.db.compat import db_manager
from common.services.order_service import OrderDetailService
from common.utils.xianyu_utils import trans_cookies


# 发货前金额刷新必须为后续流程留出时间，避免调用方 HTTP 超时（当前为 30 秒）后重试同一订单。
DELIVERY_AMOUNT_REFRESH_TIMEOUT = 15.0


class OrderActions:
    """账号级平台订单操作（依附 XianyuLive 实例共享 Cookie 与会话）"""

    def __init__(self, parent):
        self.parent = parent

    @property
    def cookie_id(self):
        return self.parent.cookie_id

    @property
    def cookies_str(self):
        return self.parent.cookies_str

    @cookies_str.setter
    def cookies_str(self, value):
        self.parent.cookies_str = value

    @property
    def cookies(self):
        return self.parent.cookies

    @cookies.setter
    def cookies(self, value):
        self.parent.cookies = value

    @property
    def session(self):
        return self.parent.session

    def _safe_str(self, obj):
        return self.parent._safe_str(obj)

    def _handle_response_cookies(self, response) -> None:
        """处理响应中的set-cookie，更新本地cookie
        
        令牌过期时服务端会在响应头中返回新的cookie（包含新的_m_h5_tk），
        存储后重试请求即可使用新的token签名
        
        Args:
            response: HTTP响应对象
        """
        try:
            from common.utils.xianyu_utils import trans_cookies
            
            if 'set-cookie' in response.headers:
                new_cookies = {}
                for cookie in response.headers.getall('set-cookie', []):
                    if '=' in cookie:
                        name, value = cookie.split(';')[0].split('=', 1)
                        new_cookies[name.strip()] = value.strip()
                
                if new_cookies:
                    existing_cookies = trans_cookies(self.cookies_str)
                    existing_cookies.update(new_cookies)
                    self.cookies_str = '; '.join([f"{k}={v}" for k, v in existing_cookies.items()])
                    self.cookies = existing_cookies
                    logger.info(f"【{self.cookie_id}】已从响应中更新Cookie（含{len(new_cookies)}个字段）")
        except Exception as e:
            logger.warning(f"【{self.cookie_id}】处理响应Cookie失败: {self._safe_str(e)}")

    async def _refresh_order_amount_before_delivery(
        self,
        order_id: str,
        item_id: str = None,
        buyer_id: str = None,
    ) -> bool:
        """发货前刷新订单详情并确认金额为正数。

        订单状态消息的详情拉取是异步的，自动发货可能在金额写入数据库前开始。
        该方法只由实际发货入口调用，用订单详情接口完成一次带令牌重试的刷新，
        随后重新读取数据库，避免用过期的 0 元缓存拦截正常订单。

        Args:
            order_id: 订单号
            item_id: 商品ID
            buyer_id: 买家ID

        Returns:
            刷新后订单金额大于 0 返回 True，否则返回 False。
        """
        try:
            detail_service = OrderDetailService(self.cookie_id, self.cookies_str)
            refreshed = await asyncio.wait_for(
                detail_service.fetch_and_update_order_detail(
                    order_id=order_id,
                    item_id=item_id,
                    buyer_id=buyer_id,
                ),
                timeout=DELIVERY_AMOUNT_REFRESH_TIMEOUT,
            )
            # 详情接口令牌过期重试后可能拿到新Cookie，立即同步到当前实例，
            # 确保后续免拼/确认发货使用新令牌，而不是继续使用旧Cookie。
            if detail_service.cookies_str and detail_service.cookies_str != self.cookies_str:
                self.cookies_str = detail_service.cookies_str
                self.cookies = trans_cookies(detail_service.cookies_str)
                logger.info(f"【{self.cookie_id}】订单 {order_id} 发货前刷新已同步最新Cookie")
            if not refreshed:
                logger.warning(f"【{self.cookie_id}】订单 {order_id} 发货前刷新订单详情未成功")
        except asyncio.TimeoutError:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 发货前刷新订单详情超时"
            )
        except Exception as e:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 发货前刷新订单详情异常: {self._safe_str(e)}"
            )

        try:
            latest_order = db_manager.get_order_by_id(order_id)
            latest_amount = latest_order.get("amount") if latest_order else None
            if latest_amount is not None and Decimal(str(latest_amount)) > 0:
                logger.info(
                    f"【{self.cookie_id}】订单 {order_id} 发货前刷新金额成功: {latest_amount}"
                )
                return True
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 发货前刷新金额解析失败: {self._safe_str(e)}"
            )
        except Exception as e:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 发货前读取最新金额异常: {self._safe_str(e)}"
            )

        return False

    async def _ensure_order_amount_before_delivery(
        self,
        order_id: str,
        item_id: str = None,
        buyer_id: str = None,
    ) -> bool:
        """发货前检查订单金额，必要时刷新订单详情。

        正常金额不会调用详情接口；只有数据库金额明确为 0 或负数时才刷新。
        订单不存在或金额为空时沿用原有流程，避免影响尚未完成建档的消息场景。

        Args:
            order_id: 订单号
            item_id: 商品ID
            buyer_id: 买家ID

        Returns:
            金额有效或无需执行金额校验返回 True，否则返回 False。
        """
        try:
            order_info = db_manager.get_order_by_id(order_id)
            if not order_info:
                return True

            order_amount = order_info.get('amount')
            if order_amount is None:
                return True

            if Decimal(str(order_amount)) > 0:
                return True
        except (InvalidOperation, TypeError, ValueError) as e:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 金额解析失败，拦截发货: {self._safe_str(e)}"
            )
            return False
        except Exception as e:
            logger.warning(
                f"【{self.cookie_id}】订单 {order_id} 发货前读取金额异常，拦截发货: {self._safe_str(e)}"
            )
            return False

        logger.warning(
            f"【{self.cookie_id}】订单 {order_id} 当前金额为 {order_amount}，发货前刷新订单详情"
        )
        return await self._refresh_order_amount_before_delivery(
            order_id=order_id,
            item_id=item_id,
            buyer_id=buyer_id,
        )

    async def auto_confirm(self, order_id, item_id=None, retry_count=0, trade_text=None):
        """在闲鱼确认发货（无物流），调用确认发货服务"""
        try:
            logger.warning(f"【{self.cookie_id}】开始确认发货，订单ID: {order_id}")

            from common.db.session import async_session_maker
            from common.db.compat import db_manager
            
            # 获取 account_pk
            account_pk = await db_manager.get_account_pk_by_cookie_id(self.cookie_id)
            if not account_pk:
                logger.error(f"【{self.cookie_id}】未找到账号信息")
                return {"error": "未找到账号信息", "order_id": order_id}

            async with async_session_maker() as db_session:
                from app.services.shipping import ConfirmShippingService
                
                # 创建确认发货服务实例
                confirm_service = ConfirmShippingService(db_session, self.session, account_pk)
                
                # 调用确认方法
                result = await confirm_service.auto_confirm(
                    order_id, item_id, retry_count, trade_text=trade_text
                )
                
                # 同步更新后的cookies
                if confirm_service.cookies_str and confirm_service.cookies_str != self.cookies_str:
                    self.cookies_str = confirm_service.cookies_str
                    self.cookies = confirm_service.cookies_dict
                    logger.warning(f"【{self.cookie_id}】已同步确认发货模块更新的cookies")

                return result

        except Exception as e:
            logger.error(f"【{self.cookie_id}】确认发货模块调用失败: {self._safe_str(e)}")
            return {"error": f"确认发货模块调用失败: {self._safe_str(e)}", "order_id": order_id}

    async def auto_freeshipping(self, order_id, item_id, buyer_id, retry_count=0):
        """小刀（砍价）订单免拼发货，调用免拼发货服务"""
        try:
            logger.warning(f"【{self.cookie_id}】开始免拼发货，订单ID: {order_id}")

            from common.db.session import async_session_maker
            from common.db.compat import db_manager
            
            # 获取 account_pk
            account_pk = await db_manager.get_account_pk_by_cookie_id(self.cookie_id)
            if not account_pk:
                logger.error(f"【{self.cookie_id}】未找到账号信息")
                return {"error": "未找到账号信息", "order_id": order_id}

            async with async_session_maker() as db_session:
                from app.services.shipping import FreeshippingService
                
                # 创建免拼发货服务实例
                freeshipping_service = FreeshippingService(db_session, self.session, account_pk)
                
                # 调用免拼发货方法
                result = await freeshipping_service.auto_freeshipping(order_id, item_id, buyer_id, retry_count)
                
                # 同步更新后的cookies
                if freeshipping_service.cookies_str and freeshipping_service.cookies_str != self.cookies_str:
                    self.cookies_str = freeshipping_service.cookies_str
                    self.cookies = freeshipping_service.cookies_dict
                    logger.warning(f"【{self.cookie_id}】已同步免拼发货模块更新的cookies")

                return result

        except Exception as e:
            logger.error(f"【{self.cookie_id}】免拼发货模块调用失败: {self._safe_str(e)}")
            return {"error": f"免拼发货模块调用失败: {self._safe_str(e)}", "order_id": order_id}

    # 订单关闭原因（闲鱼后台预设文案，不可随意修改）
    _CLOSE_ORDER_REASON = "其他原因"

    async def close_order_by_seller(self, order_no: str, retry_count: int = 0) -> bool:
        """卖家主动关闭订单

        调用闲鱼接口 mtop.taobao.idle.trade.merchant.close.by.seller 主动关闭指定订单。
        关闭原因固定为 `_CLOSE_ORDER_REASON`（"其他原因"），不接受外部传入。
        重试模式：
        - 第一次拿到的 set-cookie 通过 `_handle_response_cookies` 写回，重试时使用更新后的 cookie 重新签名
        - 接口调用失败/网络异常时最多重试 3 次

        Args:
            order_no: 订单号（同时作为 tid 和 bizOrderId）
            retry_count: 当前重试次数（递归内部使用）

        Returns:
            True 表示关闭成功，False 表示失败或异常（不抛异常，由调用方决定后续）
        """
        max_retry = 3
        close_reason = self._CLOSE_ORDER_REASON

        if not order_no:
            logger.warning(f"【{self.cookie_id}】关闭订单：order_no 为空，跳过")
            return False

        if not self.cookies_str:
            logger.warning(f"【{self.cookie_id}】关闭订单：未提供Cookie，跳过")
            return False

        try:
            from common.utils.xianyu_utils import trans_cookies, generate_sign

            cookies = trans_cookies(self.cookies_str)
            timestamp = str(int(time.time() * 1000))
            data_payload = {
                "tid": str(order_no),
                "bizOrderId": str(order_no),
                "closeReason": close_reason,
            }
            data_val = json.dumps(data_payload, separators=(',', ':'), ensure_ascii=False)

            token = cookies.get('_m_h5_tk', '').split('_')[0] if cookies.get('_m_h5_tk') else ''
            if not token:
                logger.warning(f"【{self.cookie_id}】关闭订单：Cookie中未找到 _m_h5_tk")

            sign = generate_sign(timestamp, token, data_val)

            params = {
                'jsv': '2.7.2',
                'appKey': '34839810',
                't': timestamp,
                'sign': sign,
                'v': '2.0',
                'type': 'originaljson',
                'accountSite': 'xianyu',
                'dataType': 'json',
                'timeout': '20000',
                'api': 'mtop.taobao.idle.trade.merchant.close.by.seller',
                'sessionOption': 'AutoLoginOnly',
                'spm_cnt': 'a21107h.44911108.0.0',
                'spm_pre': 'a21107h.44911108.0.0',
            }

            headers = {
                'accept': 'application/json',
                'accept-language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'cache-control': 'no-cache',
                'content-type': 'application/x-www-form-urlencoded',
                'idle_site_biz_code': 'COMMONPRO',
                'idle_user_group_member_id': '',
                'pragma': 'no-cache',
                'origin': 'https://seller.goofish.com',
                'referer': 'https://seller.goofish.com/?site=COMMONPRO&spm=a21107h.44911108.0.0',
                'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/138.0.0.0 Safari/537.36',
                'cookie': self.cookies_str.replace('\n', '').replace('\r', '') if self.cookies_str else '',
            }

            api_url = 'https://h5api.m.goofish.com/h5/mtop.taobao.idle.trade.merchant.close.by.seller/2.0/'

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    api_url,
                    params=params,
                    data={'data': data_val},
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    res_json = await response.json()

                    # 处理响应中的set-cookie，更新本地cookie（令牌过期时服务端会返回新cookie）
                    self._handle_response_cookies(response)

                    ret_list = res_json.get('ret', []) or []
                    logger.info(
                        f"【{self.cookie_id}】关闭订单：order_no={order_no}，第{retry_count + 1}次响应 ret={ret_list}"
                    )

                    if any('SUCCESS' in ret for ret in ret_list):
                        logger.warning(
                            f"【{self.cookie_id}】✅ 订单关闭成功：order_no={order_no}, reason={close_reason}"
                        )
                        return True

                    # 调用失败：使用更新后的 cookie 重试
                    if retry_count < max_retry - 1:
                        logger.info(
                            f"【{self.cookie_id}】关闭订单失败，准备重试({retry_count + 1}/{max_retry - 1})..."
                        )
                        await asyncio.sleep(0.5)
                        return await self.close_order_by_seller(order_no, retry_count + 1)

                    logger.warning(
                        f"【{self.cookie_id}】关闭订单多次失败：order_no={order_no}, ret={ret_list}"
                    )
                    return False

        except asyncio.TimeoutError:
            logger.warning(
                f"【{self.cookie_id}】关闭订单超时（第{retry_count + 1}次）：order_no={order_no}"
            )
            if retry_count < max_retry - 1:
                await asyncio.sleep(0.5)
                return await self.close_order_by_seller(order_no, retry_count + 1)
            return False
        except Exception as e:
            logger.error(
                f"【{self.cookie_id}】关闭订单异常（第{retry_count + 1}次）：order_no={order_no}, {self._safe_str(e)}"
            )
            if retry_count < max_retry - 1:
                await asyncio.sleep(0.5)
                return await self.close_order_by_seller(order_no, retry_count + 1)
            return False
