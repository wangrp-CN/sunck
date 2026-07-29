"""风险预测 schema（Phase 5 智能化预测）。

时间统一序列化为北京时间（本地 naive ISO），与项目既有 schema 约定一致。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer

from app.core.clock import LOCAL_TZ


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class ForecastOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int | None = None
    scope_type: str
    ref_id: str
    name: str | None = None
    metric: str
    horizon_days: int
    sample_count: int
    last_value: float
    slope: float
    intercept: float
    forecast_value: float
    forecast_level: str | None = None
    std_resid: float | None = None
    forecast_lower: float | None = None
    forecast_upper: float | None = None
    forecast_at: datetime
    computed_at: datetime

    @field_serializer("forecast_at", "computed_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return _ser_dt(v)
