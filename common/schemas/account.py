"""
账号相关Schema定义

功能：
1. 定义账号详情格式（AccountDetail）
2. 定义账号创建和更新请求格式
3. 兼容旧版API的数据结构
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal


class AccountDetail(BaseModel):
    """账号详情 - 兼容旧版API的数据结构"""

    pk: int  # 数据库主键
    id: str
    value: str
    enabled: bool
    scheduled_rate: bool = False
    auto_polish: bool = False
    auto_red_flower: bool = False
    ai_reply_block_ordered_users: bool = False
    remark: str | None = None
    pause_duration: int | None = None
    message_expire_time: int | None = None
    reply_delay_seconds: int | None = None
    username: str | None = None
    login_password: str | None = None
    show_browser: bool = False
    disable_reason: str | None = None
    filter_count: int = 0  # 消息过滤规则数量
    remaining_publish_capacity: int | None = None
    reserved_publish_count: int = 0


class AccountOption(BaseModel):
    """账号下拉选项"""

    pk: int
    id: str
    remark: str | None = None
    enabled: bool = True
    show_browser: bool = False
    remaining_publish_capacity: int | None = None
    reserved_publish_count: int = 0


class AccountCreate(BaseModel):
    id: str = Field(..., description="Unique account identifier provided by the user")
    value: str = Field(..., description="Raw cookie content")


class AccountCookieUpdate(BaseModel):
    value: str = Field(..., description="Updated cookie text")


class AccountStatusUpdate(BaseModel):
    enabled: bool


class AccountBatchIdsUpdate(BaseModel):
    account_ids: list[str]


class AccountBatchStatusUpdate(BaseModel):
    account_ids: list[str]
    enabled: bool


class AccountRemarkUpdate(BaseModel):
    remark: str


class AccountPublishCapacityUpdate(BaseModel):
    remaining_publish_capacity: int = Field(..., ge=0, description="当前账号剩余可发布数量")


class AccountPublishCapacityResolution(BaseModel):
    outcome: Literal["success", "failed"]
    item_id: str | None = Field(None, max_length=64)


class AccountPauseDurationUpdate(BaseModel):
    pause_duration: int = Field(..., ge=0, le=3600)


class AccountLoginInfoUpdate(BaseModel):
    """账号登录信息更新"""
    username: str | None = Field(None, description="登录用户名")
    login_password: str | None = Field(None, description="登录密码")
    show_browser: bool | None = Field(None, description="是否显示浏览器")


class AccountMessageExpireTimeUpdate(BaseModel):
    """相同消息等待时间更新"""
    message_expire_time: int = Field(..., ge=0, le=86400, description="相同消息等待时间(秒)，范围0-86400，0表示不限制")


class AccountReplyDelayUpdate(BaseModel):
    """自动回复延迟时间更新"""
    reply_delay_seconds: int = Field(..., ge=0, le=3600, description="自动回复延迟时间(秒)，范围0-3600，0表示立即回复")


class AccountScheduledRateUpdate(BaseModel):
    """定时补评价开关更新"""
    scheduled_rate: bool = Field(..., description="定时补评价开关")



class AccountAutoPolishUpdate(BaseModel):
    """商品自动擦亮开关更新"""
    auto_polish: bool = Field(..., description="商品自动擦亮开关")


class AccountAutoRedFlowerUpdate(BaseModel):
    """自动求小红花开关更新"""
    auto_red_flower: bool = Field(..., description="自动求小红花开关")


class AccountAiReplyBlockOrderedUsersUpdate(BaseModel):
    """已下单用户禁止AI回复开关更新"""
    ai_reply_block_ordered_users: bool = Field(..., description="已下单用户禁止AI回复开关")
