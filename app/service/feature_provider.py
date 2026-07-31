"""外部特征提供者与特征工程（预测特征工程：突破单序列）。

将预测从「仅用 risk_health_snapshot 单序列」升级为「单序列 + 外部特征」融合：

- :class:`MockExternalProvider`：确定性季节性合成特征（温度/降雨/风速/施工强度/设备负载），
  按 ``project_id`` 播种，保证可复现；作为默认数据源，无需任何外部凭据即可跑通整条管道。
- :class:`RealWeatherProvider`：预留真实气象 API 接入接口（和风/OpenWeather 等），
  读取 ``settings.weather_api_key``；未实现时显式抛错，避免静默错误。
- :func:`get_feature_provider`：按配置返回 provider（有 key 走真实 API，否则 Mock）。
- :func:`backfill_to_db`：把 provider 产出落 external_feature 表（幂等 upsert）。
- :class:`FeatureEngineer`：把日期序列 + 外部特征组装成回归矩阵（日历 + 外部特征）。

外部特征统一命名见 :data:`FEATURE_NAMES`。所有特征均为纯 Python 计算，无第三方依赖。
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Protocol, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.model.feature import ExternalFeature
from app.model.project import Project

# 标准外部特征名（provider 产出、回归模型消费的同一套）
FEATURE_NAMES: tuple[str, ...] = (
    "temperature",
    "rainfall",
    "wind_speed",
    "construction_intensity",
    "device_load",
)

# 回归矩阵中除外部特征外的派生列（日历特征）
CALENDAR_FEATURES: tuple[str, ...] = ("dow", "month", "is_weekend")


class FeatureProvider(Protocol):
    """特征数据源协议：给定项目与时间范围，返回 [(日期, 特征名, 值), ...]。"""

    source_name: str

    def fetch(self, project_id: int, start: date, end: date) -> list[tuple[date, str, float]]: ...


def _daterange(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


class MockExternalProvider:
    """确定性季节性合成外部特征（默认数据源，无需凭据）。

    以 ``project_id`` 为相位偏移，使不同项目特征各异但可复现；温度按年周期正弦、
    降雨为稀疏脉冲、风速低幅波动、施工强度工作日高/周末低、设备负载随施工强度变化。
    """

    source_name = "mock"

    def fetch(self, project_id: int, start: date, end: date) -> list[tuple[date, str, float]]:
        out: list[tuple[date, str, float]] = []
        pid = int(project_id) % 1000
        for d in _daterange(start, end):
            doy = d.timetuple().tm_yday
            # 温度：年周期 + 项目相位
            temp = (
                15.0
                + 12.0 * math.sin(2 * math.pi * (doy - 100) / 365.0)
                + 4.0 * math.sin(pid * 0.7 + doy * 0.1)
            )
            # 降雨：稀疏脉冲（正弦平方高值时才落雨）
            rain = max(0.0, 8.0 * math.sin(pid + doy * 0.3) ** 2 - 6.0)
            # 风速：低幅波动
            wind = 3.0 + 2.0 * math.sin(doy * 0.05 + pid)
            dow = d.weekday()
            # 施工强度：工作日高、周末低
            cons = (60.0 if dow < 5 else 20.0) + 10.0 * math.sin(pid * 0.3 + doy * 0.07)
            cons = max(0.0, cons)
            # 设备负载：随施工强度相关 + 轻微噪声
            load = max(0.0, 0.4 + 0.004 * cons + 0.05 * math.sin(doy * 0.11 + pid))
            out.extend(
                [
                    (d, "temperature", round(temp, 2)),
                    (d, "rainfall", round(rain, 2)),
                    (d, "wind_speed", round(wind, 2)),
                    (d, "construction_intensity", round(cons, 2)),
                    (d, "device_load", round(load, 3)),
                ]
            )
        return out


class RealWeatherProvider:
    """预留真实气象 API 接入接口（需配置 ``settings.weather_api_key``）。

    按项目经纬度（Project.lat/lng）向气象服务（如和风天气/OpenWeatherMap）批量拉取
    历史/预报，并映射为标准特征名。当前未实现：显式抛错，避免静默返回空数据。
    """

    source_name = "real"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def fetch(self, project_id: int, start: date, end: date) -> list[tuple[date, str, float]]:
        # TODO: 调用真实气象服务。需：项目经纬度 + 历史/预报端点 + 字段映射。
        raise NotImplementedError(
            "真实气象 API 未接入：请实现 fetch 并配置 settings.weather_api_key"
        )


def get_feature_provider() -> FeatureProvider:
    """按配置返回特征数据源：有 weather_api_key 走真实 API，否则 Mock。"""
    key = getattr(settings, "weather_api_key", "")
    if key:
        return RealWeatherProvider(key)
    return MockExternalProvider()


def backfill_to_db(
    db: Session,
    project_ids: Iterable[int],
    start: date,
    end: date,
    provider: FeatureProvider | None = None,
    source: str | None = None,
) -> int:
    """把 provider 产出幂等写入 external_feature 表，返回写入行数。"""
    provider = provider or get_feature_provider()
    src = source or provider.source_name
    rows = []
    for pid in set(project_ids):
        for d, name, val in provider.fetch(pid, start, end):
            rows.append(
                {
                    "project_id": pid,
                    "feature_date": d,
                    "feature_name": name,
                    "feature_value": float(val),
                    "source": src,
                }
            )
    if not rows:
        return 0
    stmt = pg_insert(ExternalFeature).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["project_id", "feature_date", "feature_name"],
        set_={"feature_value": stmt.excluded.feature_value, "source": stmt.excluded.source},
    )
    db.execute(stmt)
    db.flush()
    return len(rows)


def load_external_dict(
    db: Session, project_id: int, start: date, end: date
) -> dict[str, dict[str, float]]:
    """从库读取外部特征为 {日期iso: {特征名: 值}}，供回归模型对齐。"""
    rows = db.execute(
        select(
            ExternalFeature.feature_date,
            ExternalFeature.feature_name,
            ExternalFeature.feature_value,
        ).where(
            ExternalFeature.project_id == project_id,
            ExternalFeature.feature_date >= start,
            ExternalFeature.feature_date <= end,
        )
    ).all()
    out: dict[str, dict[str, float]] = {}
    for d, name, val in rows:
        out.setdefault(d.isoformat(), {})[name] = float(val)
    return out


class FeatureEngineer:
    """把日期序列 + 外部特征组装成回归设计矩阵（日历特征 + 外部特征）。

    每行特征向量（含截距列 1.0）：
    [1.0, dow, month, is_weekend, temperature, rainfall, wind_speed,
     construction_intensity, device_load]
    缺失的外部特征补 0.0（由调用方决定是否退化为纯时序模型）。
    """

    REG_FEATURES: tuple[str, ...] = (
        "dow",
        "month",
        "is_weekend",
        "temperature",
        "rainfall",
        "wind_speed",
        "construction_intensity",
        "device_load",
    )

    @staticmethod
    def row_for(d: date, ext: dict[str, float]) -> list[float]:
        return [
            1.0,  # 截距
            float(d.weekday()),
            float(d.month),
            1.0 if d.weekday() >= 5 else 0.0,
            float(ext.get("temperature", 0.0)),
            float(ext.get("rainfall", 0.0)),
            float(ext.get("wind_speed", 0.0)),
            float(ext.get("construction_intensity", 0.0)),
            float(ext.get("device_load", 0.0)),
        ]

    @classmethod
    def build_matrix(
        cls, dates: Sequence[date], external: dict[str, dict[str, float]]
    ) -> list[list[float]]:
        return [cls.row_for(d, external.get(d.isoformat(), {})) for d in dates]


def active_project_ids(db: Session) -> list[int]:
    """返回所有未删除项目的 id（回填特征用）。"""
    return list(db.execute(select(Project.id).where(Project.is_deleted.is_(False))).scalars().all())


def ensure_external_features(
    db: Session,
    days: int | None = None,
    provider: FeatureProvider | None = None,
) -> int:
    """保证近 ``days`` 天外部特征已落库；缺失则回填。返回本次写入行数。"""
    days = days or getattr(settings, "feature_backfill_days", 365)
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days)
    pids = active_project_ids(db)
    # 已存在特征的项目跳过整段回填（按项目+日期范围粗判）
    existing = (
        db.execute(
            select(ExternalFeature.project_id)
            .where(
                ExternalFeature.project_id.in_(pids),
                ExternalFeature.feature_date >= start,
                ExternalFeature.feature_date <= today,
            )
            .distinct()
        )
        .scalars()
        .all()
    )
    missing = [p for p in pids if p not in set(existing)]
    if not missing:
        return 0
    return backfill_to_db(db, missing, start, today, provider=provider)
