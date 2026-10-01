"""Single-request offline adapter; no success inference from aggregate counts."""
from __future__ import annotations

def classify_offline_response(result: dict, item_id: str) -> str:
    if result.get("_request_status_unknown"):
        return "unknown"
    raw = result.get("res")
    if not isinstance(raw, dict):
        return "unknown"
    ret = raw.get("ret")
    if not isinstance(ret, list) or len(ret) != 1 or not isinstance(ret[0], str):
        return "unknown"
    code = ret[0].partition("::")[0]
    if code.startswith("FAIL_"):
        return "failed"
    if code != "SUCCESS":
        return "unknown"
    data = raw.get("data")
    if not isinstance(data, dict) or data.get("code") != "success":
        return "unknown"
    inner = data.get("data")
    rows = inner.get("itemProcessResultList") if isinstance(inner, dict) else None
    if not isinstance(rows, list):
        return "unknown"
    matches = [r for r in rows if isinstance(r, dict) and str(r.get("itemId")) == item_id]
    if len(matches) != 1 or type(matches[0].get("success")) is not bool:
        return "unknown"
    return "success" if matches[0]["success"] else "failed"

async def offline_listing(account_id, cookies_str, item_id, owner_id, request_guard):
    from common.services.xianyu_mtop import mtop_call
    result = await mtop_call(
        account_id=account_id, cookies_str=cookies_str,
        api="mtop.alibaba.idle.seller.pc.item.batch.offline",
        version="1.0", data={"itemIds": item_id}, owner_id=owner_id,
        referer="https://seller.goofish.com/?site=COMMONPRO",
        extra_headers={"idle_site_biz_code": "COMMONPRO"}, request_guard=request_guard,
    )
    status = classify_offline_response(result, item_id)
    return {"status": status, "message": {
        "success": "平台已确认下架", "failed": "平台明确拒绝下架，请检查账号或商品后重试",
        "unknown": "下架结果未知，请核对平台状态，禁止自动重发",
    }[status]}
async def relist_listing(account_id, cookies_str, item_id, owner_id, request_guard):
    """Return a closed capability boundary until a verified relist protocol exists.

    The durable executor can still be exercised with an injected adapter in
    offline tests. The default implementation deliberately sends no request
    and never claims that a listing was recovered.
    """
    return {
        "status": "failed",
        "capability_unavailable": True,
        "message": "平台恢复接口未核验，未发送请求；请配置已核验的 relist 适配器",
    }
