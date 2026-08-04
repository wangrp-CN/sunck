"""报告订阅相关 Schema（分页响应）。

``SubscriptionOut`` 字段与 ``ReportSubscription.to_dict`` 保持一致（时间字段为 ISO
字符串），便于前端直接消费，避免重复解析。
"""

from pydantic import BaseModel, Field


class SubscriptionOut(BaseModel):
    """订阅对外输出（与 ReportSubscription.to_dict 字段一致）。"""

    id: int
    user_id: int
    name: str
    fmt: str
    days: int
    project_id: int | None = None
    frequency: str
    send_hour: int
    send_weekday: int
    send_day: int
    channels: list[str] = Field(default_factory=list)
    enabled: bool
    last_run_at: str | None = None
    last_status: str | None = None
    last_error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class SubscriptionPage(BaseModel):
    """订阅分页结果。"""

    items: list[SubscriptionOut]
    total: int
    page: int
    size: int
