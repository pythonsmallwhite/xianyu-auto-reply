"""
认证API路由

功能：
1. 用户登录（用户名+密码）
2. 令牌验证
3. 用户注册
4. 用户登出
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.core.security import decode_token
from common.models.user import User, UserRole, UserStatus
from common.schemas.auth import LoginRequest, LoginResponse, VerifyResponse
from common.schemas.common import ApiResponse
from common.schemas.user import UserCreate, UserPublic
from app.services.auth import AuthService
from app.services.user_service import UserService

router = APIRouter(tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login_user(
    payload: LoginRequest,
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> LoginResponse:
    user: User | None = None
    error_message: str | None = None

    if payload.username and payload.password:
        user, error_message = await auth_service.authenticate_by_username(payload.username, payload.password)
    elif payload.email and payload.password:
        user, error_message = await auth_service.authenticate_by_email(payload.email, payload.password)
    else:
        return LoginResponse(success=False, message="请提供有效的登录信息")

    if not user:
        return LoginResponse(success=False, message=error_message or "登录失败")

    if user.status != UserStatus.ACTIVE:
        return LoginResponse(success=False, message="账号已禁用，请联系管理员")

    await auth_service.mark_login(user)
    return LoginResponse(
        success=True,
        message="登录成功",
        token=auth_service.create_access_token(user),
        refresh_token=auth_service.create_refresh_token(user),
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.get("/verify", response_model=VerifyResponse)
async def verify_token(
    request: Request,
    session: AsyncSession = Depends(deps.get_db_session),
) -> VerifyResponse:
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return VerifyResponse(authenticated=False)

    token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(token)
    except ValueError:
        return VerifyResponse(authenticated=False)

    sub = payload.get("sub")
    if not sub:
        return VerifyResponse(authenticated=False)

    user = await session.get(User, int(sub))
    if not user or user.status != UserStatus.ACTIVE:
        return VerifyResponse(authenticated=False)

    return VerifyResponse(
        authenticated=True,
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.post("/logout", response_model=ApiResponse)
async def logout_user() -> ApiResponse:
    return ApiResponse(success=True, message="已退出登录")


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    session: AsyncSession = Depends(deps.get_db_session),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> LoginResponse:
    """刷新访问令牌"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return LoginResponse(success=False, message="未提供刷新令牌")

    refresh_token = auth_header.split(" ", 1)[1]
    try:
        payload = decode_token(refresh_token)
    except ValueError:
        return LoginResponse(success=False, message="刷新令牌无效")

    if payload.get("type") != "refresh":
        return LoginResponse(success=False, message="令牌类型错误")

    sub = payload.get("sub")
    if not sub:
        return LoginResponse(success=False, message="刷新令牌无效")

    user = await session.get(User, int(sub))
    if not user or user.status != UserStatus.ACTIVE:
        return LoginResponse(success=False, message="用户不存在或已被禁用")

    return LoginResponse(
        success=True,
        message="令牌刷新成功",
        token=auth_service.create_access_token(user),
        refresh_token=auth_service.create_refresh_token(user),
        user_id=user.id,
        username=user.username,
        is_admin=user.role == UserRole.ADMIN,
        account_limit=user.account_limit,
    )


@router.get("/check-default-password", response_model=ApiResponse)
async def check_default_password(
    current_user: User = Depends(deps.get_current_admin_user),
    auth_service: AuthService = Depends(deps.get_auth_service),
) -> ApiResponse:
    """检查管理员密码是否为默认值（admin123），仅管理员可调用"""
    is_default = auth_service._verify_user_password(current_user, "admin123")
    return ApiResponse(
        success=True,
        message="检查完成",
        data={"is_default": is_default},
    )


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: UserCreate,
    user_service: UserService = Depends(deps.get_user_service),
) -> ApiResponse:
    existing = await user_service.get_by_username(payload.username)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已被注册")

    if payload.email:
        existing_email = await user_service.get_by_email(payload.email)
        if existing_email:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="邮箱已被注册")

    await user_service.create(payload)
    return ApiResponse(success=True, message="注册成功")
