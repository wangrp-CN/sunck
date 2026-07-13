"""FastAPI 依赖注入：当前用户解析、角色/权限访问控制。

- get_current_user：解码访问令牌并从库加载用户，校验状态与锁定。
- get_current_active_superuser：超级管理员专用。
- require_permissions(*codes)：接口需具备所列权限之一（超级管理员自动通过）。
- require_roles(*codes)：接口需具备所列角色之一（超级管理员自动通过）。
"""

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, resolve_data_scope
from app.core.database import get_db
from app.core.security import decode_token
from app.model.system import User

_bearer = HTTPBearer(auto_error=False)


def get_token_payload(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> dict:
    """解析 Bearer 令牌负载，缺失或非法直接 401。"""
    if creds is None or not creds.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")
    try:
        return decode_token(creds.credentials, expected_type="access")
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")


def get_current_user(
    db: Annotated[Session, Depends(get_db)],
    payload: Annotated[dict, Depends(get_token_payload)],
) -> User:
    """根据令牌加载当前用户，并校验存在性/启用状态/锁定状态。"""
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌缺少用户标识")
    user = db.get(User, int(sub))
    if user is None or user.is_deleted:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已被删除")
    if not user.status:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已被禁用")
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_423_LOCKED, detail="账户已被锁定，请稍后重试")
    return user


def get_current_active_superuser(
    current: Annotated[User, Depends(get_current_user)],
) -> User:
    """超级管理员依赖（用于系统级危险操作）。"""
    if not current.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要超级管理员权限")
    return current


def require_permissions(*codes: str):
    """生成依赖：当前用户需拥有所列权限之一（超级管理员自动通过）。"""

    def _dep(current: Annotated[User, Depends(get_current_user)]) -> User:
        if current.is_superuser:
            return current
        if not set(codes) & set(current.permission_codes):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要以下权限之一：{', '.join(codes)}",
            )
        return current

    return _dep


def require_roles(*codes: str):
    """生成依赖：当前用户需拥有所列角色之一（超级管理员自动通过）。"""

    def _dep(current: Annotated[User, Depends(get_current_user)]) -> User:
        if current.is_superuser:
            return current
        if not set(codes) & set(current.role_codes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="角色权限不足")
        return current

    return _dep


def get_data_scope(
    current: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataScope:
    """解析当前用户的数据范围（部门数据隔离）。

    在业务查询中配合 app.core.data_scope.apply_data_scope 使用。
    """
    return resolve_data_scope(current, db)


__all__ = [
    "get_db",
    "get_current_user",
    "get_current_active_superuser",
    "require_permissions",
    "require_roles",
    "get_data_scope",
]
