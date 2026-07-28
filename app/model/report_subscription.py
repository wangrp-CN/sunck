"""定期订阅推送域模型（模块①·报告与触达增强）。

用户可按自身数据范围订阅「闭环效能运营报告」的定期生成与触达：

- 每个订阅归属一个用户（``user_id``），报告按**订阅人自身数据范围**生成（不越权）；
- 调度方式用直观的 ``frequency``(daily/weekly/monthly) + ``send_hour``(北京时) +
  ``send_weekday``(weekly) / ``send_day``(monthly)，避免裸 cron 表达式；
- 触达渠道 ``channels`` 复用通知中心 NOTIFIERS（in_app 真实，sms/voice 预留）；
- 运行记录 ``last_run_at/last_status/last_error`` 便于排障与「本周期是否已过」判断。
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin

# 频率枚举值（与 is_due 判定一致）
FREQ_DAILY = "daily"
FREQ_WEEKLY = "weekly"
FREQ_MONTHLY = "monthly"
FREQ_VALUES = (FREQ_DAILY, FREQ_WEEKLY, FREQ_MONTHLY)


class ReportSubscription(Base, TimestampMixin):
    __tablename__ = "report_subscription"

    # id / created_at / updated_at 由 Base + TimestampMixin 提供

    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="订阅归属用户（报告按该用户数据范围生成）",
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="订阅名称")
    fmt: Mapped[str] = mapped_column(
        String(8), default="excel", nullable=False, comment="报告格式 excel|pdf"
    )
    days: Mapped[int] = mapped_column(Integer, default=30, nullable=False, comment="统计窗口(天)")
    project_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="聚焦项目(留空=全量)"
    )

    # --- 调度 ---
    frequency: Mapped[str] = mapped_column(
        String(8), default=FREQ_DAILY, nullable=False, comment="daily|weekly|monthly"
    )
    send_hour: Mapped[int] = mapped_column(
        Integer, default=8, nullable=False, comment="发送时刻(北京时,0-23)"
    )
    send_weekday: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="weekly 发送星期(0=周一..6=周日)"
    )
    send_day: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, comment="monthly 发送日(1-28)"
    )
    channels: Mapped[list[str]] = mapped_column(
        JSON, default=list, nullable=False, comment="触达渠道[in_app/sms/voice]"
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True, comment="是否启用"
    )

    # --- 运行记录 ---
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最近一次运行时刻"
    )
    last_status: Mapped[str | None] = mapped_column(
        String(8), nullable=True, comment="ok|failed|skipped"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最近一次失败原因")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "fmt": self.fmt,
            "days": self.days,
            "project_id": self.project_id,
            "frequency": self.frequency,
            "send_hour": self.send_hour,
            "send_weekday": self.send_weekday,
            "send_day": self.send_day,
            "channels": self.channels,
            "enabled": self.enabled,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "last_status": self.last_status,
            "last_error": self.last_error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
