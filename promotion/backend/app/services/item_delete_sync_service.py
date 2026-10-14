"""
返佣系统 - 商品删除后同步清理服务

功能：
1. 闲鱼平台商品删除成功后，同步清理主项目数据库中的关联数据
2. 删除 xy_catalog_items 中的商品记录
"""
from __future__ import annotations

from loguru import logger
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession


async def sync_delete_item_from_db(
    session: AsyncSession,
    owner_id: int,
    item_id: str,
) -> None:
    """
    闲鱼商品删除成功后，同步清理主项目数据库中的关联数据

    清理：xy_catalog_items（商品记录）

    Args:
        session: 数据库会话
        owner_id: 所属用户ID
        item_id: 闲鱼商品ID
    """
    from common.models.xy_catalog_item import XYCatalogItem

    if not item_id:
        return

    try:
        # 删除商品记录
        item_del_stmt = delete(XYCatalogItem).where(
            XYCatalogItem.owner_id == owner_id,
            XYCatalogItem.item_id == item_id,
        )
        item_result = await session.execute(item_del_stmt)
        item_count = item_result.rowcount
        if item_count > 0:
            logger.info(
                f"用户{owner_id} 商品[{item_id}] 同步删除商品记录 {item_count} 条"
            )

        # 统一提交不在此处，由调用方统一管理事务
    except Exception as e:
        logger.error(
            f"用户{owner_id} 商品[{item_id}] 同步清理数据库异常: {e}"
        )
