"""安全工具：密码哈希、JWT 签发/校验（含访问令牌与刷新令牌）。

仅包含可复用的密码学与令牌能力，不含登录业务流程（见 app/api/v1/auth.py）。
依赖：passlib[bcrypt] + PyJWT。
"""

import re
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 令牌类型声明，用于区分访问令牌与刷新令牌
ACCESS_TOKEN_TYPE = "access"
REFRESH_TOKEN_TYPE = "refresh"


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。"""
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return _pwd_context.verify(plain, hashed)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    subject: str | int,
    expires_minutes: int | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """签发访问令牌（默认有效期取自 settings.access_token_expire_minutes）。"""
    expire = _now() + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": ACCESS_TOKEN_TYPE,
        "iat": _now(),
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def create_refresh_token(subject: str | int) -> str:
    """签发刷新令牌（有效期取自 settings.refresh_token_expire_days）。"""
    expire = _now() + timedelta(days=settings.refresh_token_expire_days)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": REFRESH_TOKEN_TYPE,
        "iat": _now(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """校验并解码 JWT，失败抛出 jwt.PyJWTError 子类。"""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    """解码令牌，并可强制校验令牌类型（访问/刷新）。"""
    payload = decode_access_token(token)
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("令牌类型不匹配")
    return payload


_PASSWORD_RULES = (
    ("password_require_upper", r"[A-Z]", "包含大写字母"),
    ("password_require_lower", r"[a-z]", "包含小写字母"),
    ("password_require_digit", r"\d", "包含数字"),
    ("password_require_special", r"[^\w\s]", "包含特殊字符"),
)


def validate_password_strength(password: str) -> None:
    """校验密码复杂度，不满足时抛出 ValueError（中文提示）。

    规则取自 settings：最小长度 + 大小写/数字/特殊字符开关。
    调用方应将 ValueError 转为业务错误响应。
    """
    if not password or len(password) < settings.password_min_length:
        raise ValueError(f"密码长度至少 {settings.password_min_length} 位")
    for flag, pattern, hint in _PASSWORD_RULES:
        if getattr(settings, flag) and not re.search(pattern, password):
            raise ValueError(f"密码需{hint}")
    # 常见弱密码黑名单（轻量）
    if password.lower() in {"password", "12345678", "qwerty12", "admin123"}:
        raise ValueError("密码过于常见，请更换")
