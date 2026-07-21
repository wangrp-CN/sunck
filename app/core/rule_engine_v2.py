"""规则引擎 v2（计划感知）：把围栏/间距/设备判定与「作业计划」绑定。

与 v1（全局：项目内所有启用围栏 + 全部大机最新位置）不同，v2 仅对
「激活中(已启动、状态=执行中、处于时间窗内) 且覆盖该设备」的作业计划产生告警，
并据每个计划的：

  - 绑定围栏集合（WorkPlanFence）     —— 仅判定计划内围栏，而非项目全部围栏
  - 绑定参考大机（WorkPlanDevice）    —— 仅与计划内大机计算间距
  - trigger_conditions               —— 门控开启哪些告警类型
  - dwell_time(停留秒)               —— 持续违规达该时长才产生告警（降误报）
  - plan_start/plan_end 时间窗        —— 时间范围门控

每条产生的告警候选携带 work_plan_id，实现告警→业务溯源。
pipeline 改用本模块 build_alarm_candidates_v2 作为判定入口。

坐标统一 WGS-84（内部判定），展示层再转 GCJ-02。
"""

import json
import logging
import time
from datetime import datetime
from typing import Any

from shapely import Point, wkt
from sqlalchemy import select

from app.core.clock import ensure_aware_local, now_local
from app.core.constants import (
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    DEVICE_STATUS_OFFLINE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
)
from app.core.geo import haversine_meters
from app.core.redis import get_redis_client
from app.model.alarm import AlarmConfig
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanDevice, WorkPlanFence
from app.service.location_service import latest_locations

logger = logging.getLogger("rail_monitor.rule_engine_v2")

#: 默认（未配置 trigger_conditions 时）开启的全部告警类型。
_DEFAULT_TRIGGERS = [ALARM_TYPE_FENCE, ALARM_TYPE_DISTANCE, ALARM_TYPE_DEVICE]

#: 默认间距阈值（米），当 alarm_config 缺失时使用
DEFAULT_DISTANCE_MACHINE = 50


def _distance_threshold(db) -> float:
    """读取 AlarmConfig 的间距阈值；缺失时回落默认。"""
    row = db.scalar(select(AlarmConfig))
    if row is None:
        return DEFAULT_DISTANCE_MACHINE
    return float(getattr(row, "distance_machine", DEFAULT_DISTANCE_MACHINE))


def _join_media(parsed: dict) -> str | None:
    """拼接上行报文中的图片/视频地址，以分号分隔。"""
    parts = [p for p in (parsed.get("image"), parsed.get("video")) if p]
    return ";".join(parts) if parts else None


# ---------------------------------------------------------------------------
# 纯函数（便于离线单测，不依赖数据库）
# ---------------------------------------------------------------------------


def parse_plan_rule(raw: Any) -> dict:
    """解析计划规则 JSON 为结构化 dict。

    兼容旧版单数 trigger_condition；缺失字段以 None 填充。
    返回 {monitor_target, trigger_conditions, dwell_time}。
    """
    if raw is None:
        return {"monitor_target": None, "trigger_conditions": None, "dwell_time": None}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {"monitor_target": None, "trigger_conditions": None, "dwell_time": None}
    if not isinstance(raw, dict):
        return {"monitor_target": None, "trigger_conditions": None, "dwell_time": None}
    tc = raw.get("trigger_conditions")
    if not tc:
        legacy = raw.get("trigger_condition")
        if legacy:
            tc = [legacy] if isinstance(legacy, str) else list(legacy)
    dwell = raw.get("dwell_time")
    if dwell is not None:
        try:
            dwell = int(dwell)
        except (TypeError, ValueError):
            dwell = None
    return {
        "monitor_target": raw.get("monitor_target"),
        "trigger_conditions": tc,
        "dwell_time": dwell,
    }


def is_plan_active_now(plan: Any, now: datetime | None = None) -> bool:
    """判断计划此刻是否激活（纯函数，作用于任何含相关属性的对象）。

    - is_start 必须为 True
    - status 必须为「执行中」
    - 若设置 plan_start/plan_end，now 须落在其闭区间内

    #11 深化后 ``plan_start/plan_end`` 为 timestamptz（aware）。统一用 aware 比较：
    now 缺省取 ``now_local()``（aware 北京）；plan 的起止时间经 ``ensure_aware_local``
    补全为 aware（兼容仍为 naive 的测试/Pydantic 对象）。两侧同为 aware 北京，
    与引擎 session timezone=Asia/Shanghai 一致，消除对服务器 locale 的依赖。
    """
    now = ensure_aware_local(now or now_local())
    if not getattr(plan, "is_start", False):
        return False
    if getattr(plan, "status", None) != "执行中":
        return False
    ps = ensure_aware_local(getattr(plan, "plan_start", None))
    pe = ensure_aware_local(getattr(plan, "plan_end", None))
    if ps is not None and now < ps:
        return False
    if pe is not None and now > pe:
        return False
    return True


def plan_covers_device(bound_nos: list[str], device_no: str) -> bool:
    """计划是否覆盖该设备（纯函数）。

    - 未绑定任何具体设备 => 项目级全覆盖
    - 否则按 device_no 命中
    """
    if not bound_nos:
        return True
    return device_no in bound_nos


def fence_geometry_contains(fence: Any, lng: float | None, lat: float | None) -> bool:
    """判断点是否落入围栏多边形（纯函数，依赖 shapely）。"""
    if lng is None or lat is None or not getattr(fence, "geometry_wkt", None):
        return False
    try:
        poly = wkt.loads(fence.geometry_wkt)
        return poly.contains(Point(lng, lat))
    except Exception as exc:  # noqa: BLE001
        logger.warning("围栏 %s 几何判定异常: %s", getattr(fence, "name", "?"), exc)
        return False


# ---------------------------------------------------------------------------
# DB 耦合部分
# ---------------------------------------------------------------------------


def _plan_covers_device(db, plan_id: int, device_no: str) -> bool:
    nos = db.scalars(
        select(WorkPlanDevice.device_no).where(WorkPlanDevice.plan_id == plan_id)
    ).all()
    return plan_covers_device(list(nos), device_no)


def _plan_fences(db, plan: WorkPlan) -> list[ElectronicFence]:
    """计划绑定的启用围栏。"""
    fids = db.scalars(select(WorkPlanFence.fence_id).where(WorkPlanFence.plan_id == plan.id)).all()
    if not fids:
        return []
    fences = db.scalars(select(ElectronicFence).where(ElectronicFence.id.in_(fids))).all()
    return [f for f in fences if f.enabled and f.geometry_wkt]


def _plan_reference_machines(db, plan: WorkPlan, all_machines: list) -> list:
    """计划参考大机（用于间距判定）。

    优先取计划绑定的 anti_intrusion 设备；未绑定则回落到传入的全部大机最新位置。

    ``all_machines`` 由调用方针对**本次上行只查询一次**（`project_id` 在单次上行内恒定，
    结果对所有计划相同），避免原先「每个含间距触发的计划各查一次 latest_locations」的
    N 次放大（高频上行下尤为严重）。此处仅做计划级的设备号过滤（小表查询，开销可忽略）。
    """
    nos = db.scalars(
        select(WorkPlanDevice.device_no).where(
            WorkPlanDevice.plan_id == plan.id,
            WorkPlanDevice.device_type == DEVICE_TYPE_ANTI_INTRUSION,
        )
    ).all()
    machines = all_machines
    if nos:
        machines = [m for m in machines if m.device_no in list(nos)]
    return machines


def load_active_plans(db, project_id: int | None, device_no: str | None = None) -> list[WorkPlan]:
    """加载激活中且（在指定时）覆盖某设备的作业计划。

    - is_start=True 且 status=执行中 且未软删
    - 处于 plan_start/plan_end 时间窗内
    - device_no 给定时，计划须覆盖该设备
    """
    now = now_local()
    stmt = (
        select(WorkPlan)
        .where(WorkPlan.is_deleted.is_(False))
        .where(WorkPlan.is_start.is_(True))
        .where(WorkPlan.status == "执行中")
    )
    if project_id is not None:
        stmt = stmt.where(WorkPlan.project_id == project_id)
    plans = db.scalars(stmt).all()
    out: list[WorkPlan] = []
    for p in plans:
        if not is_plan_active_now(p, now):
            continue
        if device_no is not None and not _plan_covers_device(db, p.id, device_no):
            continue
        out.append(p)
    return out


def _dwell_ok(db, device_no: str, plan_id: int, key: str, dwell_time: int | None) -> bool:
    """停留判定：设备须持续违规 dwell_time 秒后才产生告警。

    - dwell_time<=0 / None => 立即告警
    - 首次违规记录时间戳（Redis TTL= dwell+30s）；未达时长返回 False
    """
    if not dwell_time or dwell_time <= 0:
        return True
    r = get_redis_client()
    dk = f"rule2:dwell:{device_no}:{plan_id}:{key}"
    now = time.time()
    val = r.get(dk)
    if val is None:
        r.set(dk, str(now), ex=int(dwell_time) + 30)
        return False
    try:
        first = float(val)
    except (TypeError, ValueError):
        r.set(dk, str(now), ex=int(dwell_time) + 30)
        return False
    return (now - first) >= dwell_time


def build_alarm_candidates_v2(
    db,
    *,
    device_type: str,
    device_no: str,
    device_name: str | None,
    project_id: int | None,
    parsed: dict[str, Any],
    location,
) -> list[dict]:
    """计划感知的告警候选产出（尚未落库/去重）。

    仅对激活且覆盖本设备的作业计划进行判定；候选携带 work_plan_id。
    """
    plans = load_active_plans(db, project_id, device_no)
    candidates: list[dict] = []
    lng = parsed.get("longitude")
    lat = parsed.get("latitude")
    # 间距判定所需的大机最新位置：本次上行 project_id 固定、结果对所有计划相同，
    # 仅查询 1 次（原先每含「间距」触发的计划各查 1 次 latest_locations，N 次放大）。
    # 懒加载：仅当确有间距触发时才查询，避免纯围栏/设备计划的无谓开销。
    ref_machines: list | None = None
    # 间距阈值（AlarmConfig）单次上行内恒定，同样只查 1 次。
    distance_threshold: float | None = None

    for plan in plans:
        rule = parse_plan_rule(plan.rule_json)
        triggers = rule["trigger_conditions"]
        if not triggers:
            triggers = list(_DEFAULT_TRIGGERS)
        dwell = rule["dwell_time"]

        if device_type == DEVICE_TYPE_LOCATE:
            if ALARM_TYPE_FENCE in triggers:
                for fence in _plan_fences(db, plan):
                    if fence_geometry_contains(fence, lng, lat) and _dwell_ok(
                        db, device_no, plan.id, f"fence:{fence.id}", dwell
                    ):
                        candidates.append(
                            {
                                "alarm_type": ALARM_TYPE_FENCE,
                                "alarm_info": f"人员/设备闯入围栏「{fence.name}」",
                                "fence_name": fence.name,
                                "alarm_status": "告警开始",
                                "work_plan_id": plan.id,
                            }
                        )
            if ALARM_TYPE_DISTANCE in triggers:
                if ref_machines is None:
                    ref_machines = latest_locations(
                        db, project_id=project_id, device_type=DEVICE_TYPE_ANTI_INTRUSION
                    )
                if distance_threshold is None:
                    distance_threshold = _distance_threshold(db)
                thr = distance_threshold
                for m in _plan_reference_machines(db, plan, ref_machines):
                    if (
                        m.longitude is None
                        or m.latitude is None
                        or m.status == DEVICE_STATUS_OFFLINE
                    ):
                        continue
                    d = haversine_meters(lng, lat, m.longitude, m.latitude)
                    if d < thr and _dwell_ok(db, device_no, plan.id, f"dist:{m.device_no}", dwell):
                        candidates.append(
                            {
                                "alarm_type": ALARM_TYPE_DISTANCE,
                                "alarm_info": (
                                    f"与大机「{m.device_name}」间距仅 {round(d, 1)} 米"
                                    f"（阈值 {thr:.0f} 米）"
                                ),
                                "fence_name": None,
                                "alarm_status": "告警开始",
                                "work_plan_id": plan.id,
                            }
                        )
        else:
            if ALARM_TYPE_DEVICE in triggers:
                status = parsed.get("alarm_status")
                if status and status not in ("正常",):
                    candidates.append(
                        {
                            "alarm_type": ALARM_TYPE_DEVICE,
                            "alarm_info": parsed.get("alarm_info")
                            or f"{device_type} 设备上报：{status}",
                            "fence_name": None,
                            "alarm_status": status,
                            "media_urls": _join_media(parsed),
                            "work_plan_id": plan.id,
                        }
                    )

    base = {
        "device_type": device_type,
        "device_no": device_no,
        "device_name": device_name,
        "project_id": project_id,
        "alarm_time": parsed.get("report_time"),
    }
    for c in candidates:
        c.update(base)
    return candidates


__all__ = [
    "parse_plan_rule",
    "is_plan_active_now",
    "plan_covers_device",
    "fence_geometry_contains",
    "load_active_plans",
    "build_alarm_candidates_v2",
]
