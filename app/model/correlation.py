"""跨设备根因关联：事件组聚合表（智能核心 v2 · #77）。

将一段时间内「同项目 + 同空间范围（围栏/地理网格/单机）+ 时间窗近邻」的告警
聚合成 *事件组*（CorrelatedEventGroup），用于揭示跨设备共因（如同一围栏内多台
设备短时集中告警，疑似现场作业扰动或围栏误报聚集）。

本表为**派生滚动表**：每次计算全量重算（删旧插新），`computed_at` 标记计算时刻，
不保留历史（与风险快照不同——快照需回看趋势，关联组只需反映「当前正在发生的共因」）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class CorrelatedEventGroup(Base, TimestampMixin):
    __tablename__ = "correlated_event_group"

    # 归属项目（直接列，便于数据范围按 project_id 过滤；非外键，保持派生表轻量）
    project_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, index=True, comment="归属项目ID"
    )
    project_name: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="项目名称(冗余便于展示)"
    )

    # 空间维度：fence=同围栏名 / geo=地理网格 / device=单机
    spatial_type: Mapped[str] = mapped_column(String(16), comment="空间类型(fence/geo/device)")
    scope_key: Mapped[str] = mapped_column(String(255), comment="空间聚合键(去重判据)")
    fence_name: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="围栏名称")
    grid_cell: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="地理网格ID")

    # 时间窗
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="组内最早告警时间"
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="组内最晚告警时间"
    )

    # 统计
    alarm_count: Mapped[int] = mapped_column(Integer, default=0, comment="组内告警数")
    device_count: Mapped[int] = mapped_column(Integer, default=0, comment="涉及设备数")
    is_cross_device: Mapped[bool] = mapped_column(
        Boolean, default=False, comment="是否跨设备(涉及>=2台设备)"
    )
    max_level: Mapped[str | None] = mapped_column(
        String(16), nullable=True, comment="最高告警级别(严重/警告/提示)"
    )

    # 成员明细（JSON 文本，避免额外子表；前端展开/后端成员接口按需解析）
    device_nos: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="涉及设备编号(JSON)"
    )
    levels: Mapped[str | None] = mapped_column(Text, nullable=True, comment="告警级别分布(JSON)")
    alarm_types: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="告警类型分布(JSON)"
    )
    alarm_ids: Mapped[str | None] = mapped_column(Text, nullable=True, comment="成员告警ID(JSON)")

    # 根因提示（可解释启发式）
    root_cause_hint: Mapped[str | None] = mapped_column(Text, nullable=True, comment="根因提示")

    # 计算时刻（派生表滚动标记）
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, comment="计算时刻"
    )

    __table_args__ = (Index("ix_ceg_project_computed", "project_id", "computed_at"),)

    def to_dict(self) -> dict[str, Any]:
        """序列化为 API 友好字典（JSON 文本字段解析为列表）。"""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "spatial_type": self.spatial_type,
            "scope_key": self.scope_key,
            "fence_name": self.fence_name,
            "grid_cell": self.grid_cell,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "alarm_count": self.alarm_count,
            "device_count": self.device_count,
            "is_cross_device": self.is_cross_device,
            "max_level": self.max_level,
            "device_nos": _json_list(self.device_nos),
            "levels": _json_list(self.levels),
            "alarm_types": _json_list(self.alarm_types),
            "alarm_ids": _json_list(self.alarm_ids),
            "root_cause_hint": self.root_cause_hint,
            "computed_at": self.computed_at.isoformat() if self.computed_at else None,
        }


def _json_list(s: str | None) -> list[Any]:
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else [v]
    except (json.JSONDecodeError, TypeError):
        return []
