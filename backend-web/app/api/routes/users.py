from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api import deps
from app.core.security import get_password_hash, verify_password
from common.models.user import User
from common.schemas.common import ApiResponse
from common.schemas.user import UserPublic, UserUpdate
from common.utils.security import generate_secret_key as _generate_secret_key
from app.services.user_service import UserService


router = APIRouter(tags=["users"])


class ChangePasswordRequest(BaseModel):
    """修改密码请求"""
    current_password: str
    new_password: str


@router.get("/me", response_model=UserPublic)
async def read_current_user(current_user: User = Depends(deps.get_current_active_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


# 说明：用户列表查询与用户信息（角色/状态等）修改，统一收口到带管理员鉴权的
# /api/v1/admin/users 接口（见 app/api/routes/admin.py）。
# 此处不再暴露无鉴权的 GET / 与 PATCH /{user_id}，避免越权枚举用户及提权风险。


@router.post("/change-password", response_model=ApiResponse)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(deps.get_current_active_user),
    user_service: UserService = Depends(deps.get_user_service),
) -> ApiResponse:
    """修改当前用户密码"""
    # 验证当前密码
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码不正确")
    
    # 验证新密码长度
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新密码长度不能少于6位")
    
    # 更新密码
    current_user.password_hash = get_password_hash(payload.new_password)
    await user_service.update(current_user, UserUpdate())
    
    return ApiResponse(success=True, message="密码修改成功")


@router.get("/secret-key")
async def get_secret_key(
    current_user: User = Depends(deps.get_current_active_user),
    user_service: UserService = Depends(deps.get_user_service),
):
    """获取当前用户的外部接口秘钥，若无则自动生成（32位随机字符，全局唯一）"""
    if not current_user.secret_key:
        # 自动生成秘钥，最多尝试10次避免唯一约束冲突
        for _ in range(10):
            key = _generate_secret_key()
            current_user.secret_key = key
            try:
                await user_service.update(current_user, UserUpdate())
                break
            except Exception:
                current_user.secret_key = None
                continue
        else:
            raise HTTPException(status_code=500, detail="生成外部接口秘钥失败，请重试")
    return {"success": True, "secret_key": current_user.secret_key}


@router.post("/secret-key/reset", response_model=ApiResponse)
async def reset_secret_key(
    current_user: User = Depends(deps.get_current_active_user),
    user_service: UserService = Depends(deps.get_user_service),
) -> ApiResponse:
    """更换当前用户的外部接口秘钥，生成新的32位随机字符（全局唯一）"""
    # 最多尝试10次避免唯一约束冲突
    for _ in range(10):
        key = _generate_secret_key()
        current_user.secret_key = key
        try:
            await user_service.update(current_user, UserUpdate())
            return ApiResponse(
                success=True,
                message="外部接口秘钥已更换",
                data={"secret_key": key},
            )
        except Exception:
            current_user.secret_key = None
            continue
    raise HTTPException(status_code=500, detail="更换外部接口秘钥失败，请重试")
