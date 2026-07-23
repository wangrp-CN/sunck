"""操作审计 Schema：对外输出与分页。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.clock import LOCAL_TZ


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    username: str | None = None
    dept_id: int | None = None
    action: str
    module: str
    method: str
    path: str
    query: str | None = None
    status_code: int
    ip: str | None = None
    detail: str | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class AuditLogPage(BaseModel):
    total: int
    items: list[AuditLogOut]
    page: int = 1
    size: int = 20
