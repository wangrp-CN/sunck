"""告警策略模型（🅱 告警治理与值班体系 M4：收敛/抑制/升级）。

按「项目 × 告警类型」维度配置告警治理策略：

- **收敛**：``suppress_window_seconds`` 覆盖全局风暴合并窗口（同键告警在窗口内合并）；
- **抑制（静默）**：``silence_start/silence_end``（HH:MM，支持跨天）静默时段内
  告警仍**正常落库**（不丢数据），但跳过通知打扰；
- **升级**：``escalate_after_minutes`` 超时未处理自动升级到 ``escalate_to_level``
  并按 ``escalate_channels`` 重新通知（含当班人），由周期任务驱动。

匹配优先级（``resolve_policy``）：项目+类型 > 项目通配 > 全局+类型 > 全局通配。
数据范围：经 project_id 走 VIA_PROJECT；project_id 为空表示全局策略（仅全量数据用户可见）。
"""

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.model.base import Base, CreatorMixin, SoftDeleteMixin, TimestampMixin
from app.model.project import Project


class AlarmPolicy(Base, TimestampMixin, CreatorMixin, SoftDeleteMixin):
    __tablename__ = "alarm_policy"

    name: Mapped[str] = mapped_column(String(128), comment="策略名称")
    # 归属项目：空=全局策略（对所有项目生效，被项目级策略覆盖）
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("project.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project: Mapped["Project"] = relationship("Project", lazy="selectin")
    # 告警类型：空=通配（所有类型），如 fence_intrusion / predictive_alert
    alarm_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="告警类型(空=全部)"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")

    # —— 收敛：覆盖全局 alarm_suppress_window_seconds（空=用全局默认） ——
    suppress_window_seconds: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="风暴合并窗口秒(空=全局默认)"
    )

    # —— 抑制（静默免打扰）：HH:MM 本地时间，支持跨天（如 22:00-06:00） ——
    silence_start: Mapped[str | None] = mapped_column(
        String(5), nullable=True, comment="静默开始 HH:MM"
    )
    silence_end: Mapped[str | None] = mapped_column(
        String(5), nullable=True, comment="静默结束 HH:MM"
    )

    # —— 升级：超时未处理自动升级级别并重新通知（空=不升级） ——
    escalate_after_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="超时未处理升级时限(分钟，空=不升级)"
    )
    escalate_to_level: Mapped[str] = mapped_column(
        String(16), default="严重", comment="升级目标级别"
    )
    escalate_channels: Mapped[str] = mapped_column(
        String(64), default="in_app", comment="升级通知渠道(逗号分隔 in_app/sms/voice)"
    )

    note: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")

    __table_args__ = (
        Index("ix_alarm_policy_project", "project_id"),
        Index("ix_alarm_policy_match", "project_id", "alarm_type", "enabled"),
    )
