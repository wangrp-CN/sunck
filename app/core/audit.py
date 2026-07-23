"""操作审计中间件：对写请求（POST/PUT/PATCH/DELETE）自动落审计日志。

设计要点：
- 仅记录变更类请求；GET/HEAD/OPTIONS 等只读请求与 /docs、/openapi、/metrics、
  /ws、/health 等系统端点跳过。
- 审计写库使用独立会话，且全程 try/except 包裹——**审计失败绝不阻断业务响应**。
- 操作人身份从 Bearer 令牌的 `sub` 解析；命中则快照 username / dept_id（便于按
  部门数据范围检索，与全站数据隔离一致），未命中则记匿名（如登录尝试）。
- 由 `settings.audit_enabled` 总开关控制（测试环境关闭，避免用例间审计行累积）。
"""

import logging
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.core.database import SessionLocal
from app.core.security import decode_token

logger = logging.getLogger("rail_monitor.audit")

_SKIP_PREFIXES = (
    "/docs",
    "/redoc",
    "/openapi.json",
    "/metrics",
    "/ws",
    "/health",
    "/static",
)
_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
_METHOD_ACTION = {
    "POST": "create",
    "PUT": "update",
    "PATCH": "update",
    "DELETE": "delete",
}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not settings.audit_enabled:
            return await call_next(request)
        path = request.url.path
        if request.method not in _MUTATING or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        # 预解析操作人（失败则匿名），不阻塞主流程
        user_id: int | None = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_token(auth[7:], expected_type="access")
                sub = payload.get("sub")
                if sub:
                    user_id = int(sub)
            except Exception:  # noqa: BLE001
                user_id = None

        response = await call_next(request)

        # 落审计（独立会话 + 全保护，失败仅告警）
        try:
            self._record(request, response, user_id)
        except Exception:  # noqa: BLE001
            logger.warning("审计日志写入失败（不影响业务）", exc_info=False)
        return response

    def _record(self, request: Request, response: Response, user_id: int | None) -> None:
        username: str | None = None
        dept_id: int | None = None
        if user_id is not None:
            db = SessionLocal()
            try:
                from app.model.system import User

                u = db.get(User, user_id)
                if u is not None and not u.is_deleted:
                    username = u.username
                    dept_id = u.dept_id
            finally:
                db.close()

        db = SessionLocal()
        try:
            from app.service.audit_service import write_audit_log

            module = self._module_of(request.url.path)
            action = _METHOD_ACTION.get(request.method, "other")
            ip = request.client.host if request.client else None
            query = request.url.query or None
            write_audit_log(
                db,
                user_id=user_id,
                username=username,
                dept_id=dept_id,
                action=action,
                module=module,
                method=request.method,
                path=request.url.path,
                query=query,
                status_code=response.status_code,
                ip=ip,
            )
            db.commit()
        finally:
            db.close()

    @staticmethod
    def _module_of(path: str) -> str:
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] == "api":
            # /api/v1/<module>/... 或 /api/<module>/...
            idx = 2 if len(parts) > 2 and parts[1] == "v1" else 1
            return parts[idx] if idx < len(parts) else "api"
        return parts[0] if parts else "root"
