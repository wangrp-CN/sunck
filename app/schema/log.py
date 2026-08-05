"""系统日志 Schema：对外输出与分页。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class SystemLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    module: str
    message: str
    detail: str | None = None
    traceback: str | None = None
    source: str | None = None
    user_id: int | None = None
    created_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class SystemLogPage(BaseModel):
    total: int
    items: list[SystemLogOut]
    page: int = 1
    size: int = 20


class SystemLogCreate(BaseModel):
    """写入系统日志的请求体（内部调用或管理后台补录）。"""

    level: str = Field("INFO", description="日志级别")
    module: str = Field(..., min_length=1, max_length=48, description="来源模块")
    message: str = Field(..., min_length=1, max_length=512, description="日志摘要")
    detail: str | None = Field(None, description="详细上下文")
    traceback: str | None = Field(None, description="异常堆栈")
    source: str | None = Field(None, max_length=128, description="触发来源")
    user_id: int | None = Field(None, description="关联用户ID")


class SystemLogMetaOut(BaseModel):
    """日志检索元数据：库中已出现的级别/模块集合。"""

    levels: list[str]
    modules: list[str]
