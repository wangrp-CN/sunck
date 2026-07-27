"""闭环效能度量：量化「监测 → 异常 → 告警 → 派单 → 治理」全链路的有效性。

供大屏「闭环效能」卡使用，回答四类问题：
- 风暴抑制到底压掉了多少同源重复告警（抑制率）；
- 告警平均多久被处置掉（MTTR，近似口径）；
- 派单是否在时限内闭环（SLA 达成率 + 平均闭环周期）；
- 隐患治理闭环率，以及趋势异常引擎对告警流的贡献占比。

本期增强（#82 细调）：
- **趋势对比**：每个指标附带「上一周期」环比（prev / delta_pct / direction / good），
  前端据此渲染上升/下降箭头与好坏着色（抑制率↑好、MTTR↑坏、异常占比中性）。
- **按项目下钻**：端点支持 ``project_id``，返回 ``by_project`` 各项目指标排名明细，
  点击即可把头部 5 指标切换为该项目的下钻视图。
- **时间序列 sparkline**（#83）：返回 ``series``（5 指标逐时间桶的值序列，桶步长随
  窗口长度自适应 ~30 点），供前端迷你趋势线渲染，直观看到指标随时间的走势。

所有查询经 ``apply_data_scope`` 数据范围隔离，只读（由调用方传 read 会话）。
软删除模型（dispatch_order / hazard）额外过滤 ``is_deleted``；alarm 无软删列。
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import Integer, func, select

from app.core.clock import day_end_local, day_start_local
from app.core.data_scope import DataScope, apply_data_scope
from app.model.alarm import Alarm
from app.model.dispatch import DispatchOrder
from app.model.hazard import Hazard
from app.model.project import Project

# 视为「已处置」的告警处理状态（用于 MTTR / 处置率分母）
_RESOLVED_STATUSES = ("已处理", "已忽略", "已确认")
_DISPATCH_CLOSED = "已闭环"
_HAZARD_CLOSED = "已销号"

# 空原始计数骨架（所有指标键齐全，便于聚合）
_ZERO = {
    "alarms": 0,
    "suppressed": 0,
    "resolved": 0,
    "mttr_sum_seconds": 0.0,
    "anomaly_alarms": 0,
    "d_closed": 0,
    "d_on_time": 0,
    "d_with_deadline": 0,
    "d_cycle_sum_hours": 0.0,
    "corr_dispatch": 0,
    "h_total": 0,
    "h_closed": 0,
    "h_ontime": 0,
    "h_with_due": 0,
}


def _range(days: int) -> tuple[datetime, datetime]:
    """返回 [start, end] aware 区间：end=今日北京日界末，start=end 前 days-1 天（含今日共 days 天）。"""
    end = day_end_local()
    start = day_start_local() - timedelta(days=max(days - 1, 0))
    return start, end


def _scalar_int(db, stmt) -> int:
    return int(db.scalar(stmt) or 0)


def _trend(cur, prev, higher_is_better: bool | None):
    """环比趋势：相对变化率 + 方向 + 好坏语义。

    - prev 为 0/None：无法计算相对变化 → direction=flat，good=None（或「从 0 到正数」判为上升）。
    - delta_pct：相对变化百分比（四舍五入 1 位）；good 依 higher_is_better 决定红绿。
    - higher_is_better=None（如异常占比）：中性，good 恒为 None（前端灰色）。
    """
    if prev is None or (prev == 0 and cur == 0):
        return {"prev": prev, "delta_pct": None, "direction": "flat", "good": None}
    if prev == 0:
        direction = "up" if cur > 0 else "flat"
        good = None if direction == "flat" else ((direction == "up") == higher_is_better)
        return {"prev": prev, "delta_pct": None, "direction": direction, "good": good}
    delta = (cur - prev) / prev * 100.0
    direction = "up" if delta > 0.5 else ("down" if delta < -0.5 else "flat")
    good = None if direction == "flat" else ((direction == "up") == higher_is_better)
    return {"prev": prev, "delta_pct": round(delta, 1), "direction": direction, "good": good}


def _alarm_groups(db, scope: DataScope, start, end) -> dict[int, dict]:
    """按项目聚合告警：数量、被抑制数、已处置数、MTTR 秒和、趋势异常数。"""
    stmt = (
        select(
            Alarm.project_id,
            func.count(),
            func.coalesce(func.sum(Alarm.suppressed_count), 0),
            func.count().filter(Alarm.handle_status.in_(_RESOLVED_STATUSES)),
            func.coalesce(
                func.sum(func.extract("epoch", Alarm.updated_at - Alarm.alarm_time)).filter(
                    Alarm.handle_status.in_(_RESOLVED_STATUSES)
                    & Alarm.updated_at.isnot(None)
                    & Alarm.alarm_time.isnot(None)
                    & (Alarm.updated_at >= Alarm.alarm_time)
                ),
                0,
            ),
            func.count().filter(Alarm.alarm_type == "trend_anomaly"),
        )
        .select_from(Alarm)
        .where(Alarm.alarm_time >= start)
    )
    if end is not None:
        stmt = stmt.where(Alarm.alarm_time < end)
    stmt = stmt.group_by(Alarm.project_id)
    stmt = apply_data_scope(stmt, Alarm, scope)
    out: dict[int, dict] = {}
    for pid, cnt, supp, resolved, mttr_sec, anomaly in db.execute(stmt).all():
        out[pid] = {
            "alarms": int(cnt),
            "suppressed": int(supp),
            "resolved": int(resolved),
            "mttr_sum_seconds": float(mttr_sec or 0),
            "anomaly_alarms": int(anomaly),
        }
    return out


def _dispatch_closed_groups(db, scope: DataScope, start, end) -> dict[int, dict]:
    """按项目聚合已闭环派单：闭环数、按期数、有期限数、闭环周期小时和。"""
    stmt = (
        select(
            DispatchOrder.project_id,
            func.count().filter(DispatchOrder.status == _DISPATCH_CLOSED),
            func.count().filter(
                (DispatchOrder.status == _DISPATCH_CLOSED)
                & (DispatchOrder.closed_at <= DispatchOrder.deadline)
                & DispatchOrder.deadline.isnot(None)
            ),
            func.count().filter(
                (DispatchOrder.status == _DISPATCH_CLOSED) & DispatchOrder.deadline.isnot(None)
            ),
            func.coalesce(
                func.sum(
                    func.extract("epoch", DispatchOrder.closed_at - DispatchOrder.created_at)
                    / 3600.0
                ).filter(DispatchOrder.status == _DISPATCH_CLOSED),
                0,
            ),
        )
        .select_from(DispatchOrder)
        .where(DispatchOrder.is_deleted.is_(False), DispatchOrder.closed_at >= start)
    )
    if end is not None:
        stmt = stmt.where(DispatchOrder.closed_at < end)
    stmt = stmt.group_by(DispatchOrder.project_id)
    stmt = apply_data_scope(stmt, DispatchOrder, scope)
    out: dict[int, dict] = {}
    for pid, closed, on_time, with_deadline, cycle_h in db.execute(stmt).all():
        out[pid] = {
            "d_closed": int(closed),
            "d_on_time": int(on_time),
            "d_with_deadline": int(with_deadline),
            "d_cycle_sum_hours": float(cycle_h or 0),
        }
    return out


def _dispatch_corr_groups(db, scope: DataScope, start, end) -> dict[int, dict]:
    """按项目聚合由跨设备共因发起的派单数。"""
    stmt = (
        select(DispatchOrder.project_id, func.count())
        .select_from(DispatchOrder)
        .where(
            DispatchOrder.is_deleted.is_(False),
            DispatchOrder.created_at >= start,
            DispatchOrder.source_type == "correlation",
        )
    )
    if end is not None:
        stmt = stmt.where(DispatchOrder.created_at < end)
    stmt = stmt.group_by(DispatchOrder.project_id)
    stmt = apply_data_scope(stmt, DispatchOrder, scope)
    out: dict[int, dict] = {}
    for pid, cnt in db.execute(stmt).all():
        out[pid] = {"corr_dispatch": int(cnt)}
    return out


def _hazard_groups(db, scope: DataScope, start, end) -> dict[int, dict]:
    """按项目聚合隐患：总数、已销号、按期销号、有期限数。"""
    stmt = (
        select(
            Hazard.project_id,
            func.count(),
            func.count().filter(Hazard.status == _HAZARD_CLOSED),
            func.count().filter(
                (Hazard.status == _HAZARD_CLOSED)
                & (Hazard.closed_at <= Hazard.due_at)
                & Hazard.due_at.isnot(None)
            ),
            func.count().filter((Hazard.status == _HAZARD_CLOSED) & Hazard.due_at.isnot(None)),
        )
        .select_from(Hazard)
        .where(Hazard.is_deleted.is_(False), Hazard.created_at >= start)
    )
    if end is not None:
        stmt = stmt.where(Hazard.created_at < end)
    stmt = stmt.group_by(Hazard.project_id)
    stmt = apply_data_scope(stmt, Hazard, scope)
    out: dict[int, dict] = {}
    for pid, total, closed, ontime, with_due in db.execute(stmt).all():
        out[pid] = {
            "h_total": int(total),
            "h_closed": int(closed),
            "h_ontime": int(ontime),
            "h_with_due": int(with_due),
        }
    return out


def _collect(db, scope: DataScope, start, end) -> dict[int, dict]:
    """聚合四种模型的分组结果，返回 {pid: 完整原始计数}。"""
    raw: dict[int, dict] = {}

    def acc(d: dict[int, dict]):
        for pid, vals in d.items():
            r = raw.setdefault(pid, dict(_ZERO))
            r.update(vals)

    acc(_alarm_groups(db, scope, start, end))
    acc(_dispatch_closed_groups(db, scope, start, end))
    acc(_dispatch_corr_groups(db, scope, start, end))
    acc(_hazard_groups(db, scope, start, end))
    # 补全所有键
    for pid in list(raw.keys()):
        merged = dict(_ZERO)
        merged.update(raw[pid])
        raw[pid] = merged
    return raw


def _bucket_index(col, start: datetime, bucket_days: int):
    """把时间列映射到桶序号：floor((col - start) 秒数 / bucket_days 天秒数)。"""
    return func.floor(func.extract("epoch", col - start) / (bucket_days * 86400.0)).cast(Integer)


def _collect_time_series(
    db, scope: DataScope, start, end, bucket_days: int, project_id: int | None = None
) -> dict:
    """按时间桶聚合原始计数，逐桶派生 5 项指标，供前端 sparkline（时间序列）渲染。

    - 桶网格以 ``start`` 为锚、步长 ``bucket_days`` 天，覆盖 [start, end)。
    - 4 个模型各一次 ``GROUP BY 桶序号`` 查询（共 4 次，与窗口长度无关），
      比「每桶调一次 _collect」轻量得多（后者对 30 桶要多 100+ 次查询）。
    - 返回 ``{storm,mttr,dispatch_sla,hazard,anomaly: [{t, v}]}``，v 为各桶指标值。
    """
    secs = max(1, int((end - start).total_seconds()))
    n_buckets = max(1, math.ceil(secs / (bucket_days * 86400.0)))
    raws = [dict(_ZERO) for _ in range(n_buckets)]

    # 1) 告警（抑制/处置/MTTR/趋势异常）—— 时间列 alarm_time
    stmt = (
        select(
            _bucket_index(Alarm.alarm_time, start, bucket_days),
            func.count(),
            func.coalesce(func.sum(Alarm.suppressed_count), 0),
            func.count().filter(Alarm.handle_status.in_(_RESOLVED_STATUSES)),
            func.coalesce(
                func.sum(func.extract("epoch", Alarm.updated_at - Alarm.alarm_time)).filter(
                    Alarm.handle_status.in_(_RESOLVED_STATUSES)
                    & Alarm.updated_at.isnot(None)
                    & Alarm.alarm_time.isnot(None)
                    & (Alarm.updated_at >= Alarm.alarm_time)
                ),
                0,
            ),
            func.count().filter(Alarm.alarm_type == "trend_anomaly"),
        )
        .select_from(Alarm)
        .where(Alarm.alarm_time >= start, Alarm.alarm_time < end)
        .group_by(_bucket_index(Alarm.alarm_time, start, bucket_days))
    )
    if project_id:
        stmt = stmt.where(Alarm.project_id == project_id)
    stmt = apply_data_scope(stmt, Alarm, scope)
    for idx, cnt, supp, resolved, mttr_sec, anomaly in db.execute(stmt).all():
        if 0 <= idx < n_buckets:
            raws[idx].update(
                {
                    "alarms": int(cnt),
                    "suppressed": int(supp),
                    "resolved": int(resolved),
                    "mttr_sum_seconds": float(mttr_sec or 0),
                    "anomaly_alarms": int(anomaly),
                }
            )

    # 2) 已闭环派单（SLA/周期）—— 时间列 closed_at
    stmt = (
        select(
            _bucket_index(DispatchOrder.closed_at, start, bucket_days),
            func.count().filter(DispatchOrder.status == _DISPATCH_CLOSED),
            func.count().filter(
                (DispatchOrder.status == _DISPATCH_CLOSED)
                & (DispatchOrder.closed_at <= DispatchOrder.deadline)
                & DispatchOrder.deadline.isnot(None)
            ),
            func.count().filter(
                (DispatchOrder.status == _DISPATCH_CLOSED) & DispatchOrder.deadline.isnot(None)
            ),
            func.coalesce(
                func.sum(
                    func.extract("epoch", DispatchOrder.closed_at - DispatchOrder.created_at)
                    / 3600.0
                ).filter(DispatchOrder.status == _DISPATCH_CLOSED),
                0,
            ),
        )
        .select_from(DispatchOrder)
        .where(
            DispatchOrder.is_deleted.is_(False),
            DispatchOrder.closed_at >= start,
            DispatchOrder.closed_at < end,
        )
        .group_by(_bucket_index(DispatchOrder.closed_at, start, bucket_days))
    )
    if project_id:
        stmt = stmt.where(DispatchOrder.project_id == project_id)
    stmt = apply_data_scope(stmt, DispatchOrder, scope)
    for idx, closed, on_time, with_deadline, cycle_h in db.execute(stmt).all():
        if 0 <= idx < n_buckets:
            raws[idx].update(
                {
                    "d_closed": int(closed),
                    "d_on_time": int(on_time),
                    "d_with_deadline": int(with_deadline),
                    "d_cycle_sum_hours": float(cycle_h or 0),
                }
            )

    # 3) 共因派单（异常引擎贡献）—— 时间列 created_at
    stmt = (
        select(
            _bucket_index(DispatchOrder.created_at, start, bucket_days),
            func.count(),
        )
        .select_from(DispatchOrder)
        .where(
            DispatchOrder.is_deleted.is_(False),
            DispatchOrder.created_at >= start,
            DispatchOrder.created_at < end,
            DispatchOrder.source_type == "correlation",
        )
        .group_by(_bucket_index(DispatchOrder.created_at, start, bucket_days))
    )
    if project_id:
        stmt = stmt.where(DispatchOrder.project_id == project_id)
    stmt = apply_data_scope(stmt, DispatchOrder, scope)
    for idx, cnt in db.execute(stmt).all():
        if 0 <= idx < n_buckets:
            raws[idx]["corr_dispatch"] = int(cnt)

    # 4) 隐患（闭环率）—— 时间列 created_at
    stmt = (
        select(
            _bucket_index(Hazard.created_at, start, bucket_days),
            func.count(),
            func.count().filter(Hazard.status == _HAZARD_CLOSED),
            func.count().filter(
                (Hazard.status == _HAZARD_CLOSED)
                & (Hazard.closed_at <= Hazard.due_at)
                & Hazard.due_at.isnot(None)
            ),
            func.count().filter((Hazard.status == _HAZARD_CLOSED) & Hazard.due_at.isnot(None)),
        )
        .select_from(Hazard)
        .where(Hazard.is_deleted.is_(False), Hazard.created_at >= start, Hazard.created_at < end)
        .group_by(_bucket_index(Hazard.created_at, start, bucket_days))
    )
    if project_id:
        stmt = stmt.where(Hazard.project_id == project_id)
    stmt = apply_data_scope(stmt, Hazard, scope)
    for idx, total, closed, ontime, with_due in db.execute(stmt).all():
        if 0 <= idx < n_buckets:
            raws[idx].update(
                {
                    "h_total": int(total),
                    "h_closed": int(closed),
                    "h_ontime": int(ontime),
                    "h_with_due": int(with_due),
                }
            )

    # 逐桶派生 5 指标值 + 桶起点时间戳
    series: dict[str, list[dict]] = {
        "storm": [],
        "mttr": [],
        "dispatch_sla": [],
        "hazard": [],
        "anomaly": [],
    }
    cur = start
    for i in range(n_buckets):
        raw = raws[i]
        b_start = cur
        cur = cur + timedelta(days=bucket_days)
        denom = raw["alarms"] + raw["suppressed"]
        storm = round(raw["suppressed"] / denom * 100, 1) if denom else 0.0
        resolved = raw["resolved"]
        mttr = round(raw["mttr_sum_seconds"] / 3600.0 / resolved, 1) if resolved else 0.0
        with_deadline = raw["d_with_deadline"]
        sla = round(raw["d_on_time"] / with_deadline * 100, 1) if with_deadline else 0.0
        h_total = raw["h_total"]
        closure = round(raw["h_closed"] / h_total * 100, 1) if h_total else 0.0
        anomaly = round(raw["anomaly_alarms"] / raw["alarms"] * 100, 1) if raw["alarms"] else 0.0
        t = b_start.isoformat()
        series["storm"].append({"t": t, "v": storm})
        series["mttr"].append({"t": t, "v": mttr})
        series["dispatch_sla"].append({"t": t, "v": sla})
        series["hazard"].append({"t": t, "v": closure})
        series["anomaly"].append({"t": t, "v": anomaly})
    return series


def _sum(raw: dict[int, dict]) -> dict:
    s = dict(_ZERO)
    for r in raw.values():
        for k, v in r.items():
            s[k] += v
    return s


def _accessible_projects(db, scope: DataScope) -> list[tuple[int, str]]:
    """可见项目 (id, name) 列表：is_all 取全部，否则按部门过滤，与 dashboard 同口径。"""
    stmt = select(Project.id, Project.name).where(Project.is_deleted.is_(False))
    if scope.dept_ids:
        stmt = stmt.where(Project.dept_id.in_(scope.dept_ids))
    return list(db.execute(stmt).all())


def _derive(raw: dict, prev: dict) -> dict:
    """从原始计数派生 5 项指标 + 各自环比趋势。"""
    # 1) 风暴抑制率
    denom = raw["alarms"] + raw["suppressed"]
    rate = round(raw["suppressed"] / denom * 100, 1) if denom else 0.0
    pdenom = prev["alarms"] + prev["suppressed"]
    prate = round(prev["suppressed"] / pdenom * 100, 1) if pdenom else 0.0
    storm = {
        "suppressed": raw["suppressed"],
        "alarms": raw["alarms"],
        "rate_pct": rate,
        "trend": _trend(rate, prate, True),
    }

    # 2) 告警处置 MTTR（近似）
    resolved = raw["resolved"]
    avg_h = round(raw["mttr_sum_seconds"] / 3600.0 / resolved, 1) if resolved else 0.0
    presolved = prev["resolved"]
    pavg = round(prev["mttr_sum_seconds"] / 3600.0 / presolved, 1) if presolved else 0.0
    resolution_rate = round(resolved / raw["alarms"] * 100, 1) if raw["alarms"] else 0.0
    mttr = {
        "avg_hours": avg_h,
        "resolved": resolved,
        "resolution_rate_pct": resolution_rate,
        "trend": _trend(avg_h, pavg, False),
    }

    # 3) 派单 SLA
    closed = raw["d_closed"]
    on_time = raw["d_on_time"]
    with_deadline = raw["d_with_deadline"]
    sla = round(on_time / with_deadline * 100, 1) if with_deadline else 0.0
    pon_time = prev["d_on_time"]
    pwith_deadline = prev["d_with_deadline"]
    psla = round(pon_time / pwith_deadline * 100, 1) if pwith_deadline else 0.0
    cycle = round(raw["d_cycle_sum_hours"] / closed, 1) if closed else 0.0
    dispatch_sla = {
        "closed": closed,
        "on_time": on_time,
        "sla_rate_pct": sla,
        "avg_cycle_hours": cycle,
        "trend": _trend(sla, psla, True),
    }

    # 4) 隐患治理闭环率
    h_total = raw["h_total"]
    h_closed = raw["h_closed"]
    closure = round(h_closed / h_total * 100, 1) if h_total else 0.0
    ph_total = prev["h_total"]
    ph_closed = prev["h_closed"]
    pclosure = round(ph_closed / ph_total * 100, 1) if ph_total else 0.0
    h_ontime = raw["h_ontime"]
    h_with_due = raw["h_with_due"]
    on_time_rate = round(h_ontime / h_with_due * 100, 1) if h_with_due else 0.0
    hazard = {
        "total": h_total,
        "closed": h_closed,
        "closure_rate_pct": closure,
        "on_time_rate_pct": on_time_rate,
        "trend": _trend(closure, pclosure, True),
    }

    # 5) 异常贡献（趋势异常告警占比；中性、不着色）
    anomaly_alarms = raw["anomaly_alarms"]
    share = round(anomaly_alarms / raw["alarms"] * 100, 1) if raw["alarms"] else 0.0
    panomaly_alarms = prev["anomaly_alarms"]
    pshare = round(panomaly_alarms / prev["alarms"] * 100, 1) if prev["alarms"] else 0.0
    anomaly = {
        "alarms": anomaly_alarms,
        "share_pct": share,
        "correlation_dispatches": raw["corr_dispatch"],
        "trend": _trend(share, pshare, None),
    }

    return {
        "storm": storm,
        "mttr": mttr,
        "dispatch_sla": dispatch_sla,
        "hazard": hazard,
        "anomaly": anomaly,
    }


def _risk_index(m: dict) -> tuple[float, str]:
    """项目下钻风险分：表现越差分越高（SLA/闭环率权重最大）。"""
    s = m["storm"]["rate_pct"]
    sla = m["dispatch_sla"]["sla_rate_pct"]
    cl = m["hazard"]["closure_rate_pct"]
    mt = m["mttr"]["avg_hours"]
    score = (
        (100 - s) * 0.15
        + (100 - sla) * 0.35
        + (100 - cl) * 0.35
        + (min(mt, 168) / 168 * 100) * 0.15
    )
    score = round(score, 1)
    level = "高" if score >= 60 else ("中" if score >= 30 else "低")
    return score, level


def compute_effectiveness(
    db, scope: DataScope, days: int = 30, project_id: int | None = None
) -> dict:
    """计算闭环效能指标（含环比与按项目下钻）。

    - project_id 为 None：头部 5 指标为全量聚合，by_project 返回各项目明细排名。
    - project_id 指定且可见：头部 5 指标切换为该项目的下钻视图，by_project 仍返回全量明细。
    """
    start, end = _range(days)
    prev_start = start - timedelta(days=days)
    prev_end = start  # 上一周期上界（不含）

    gc = _collect(db, scope, start, None)  # 当前窗口（无上界，与历史口径一致）
    gp = _collect(db, scope, prev_start, prev_end)  # 上一周期（等长、不含当前起点）

    overall = _sum(gc)
    overall_prev = _sum(gp)

    # 校验下钻项目可见性
    focus_pid: int | None = None
    if project_id is not None:
        visible = {pid for pid, _ in _accessible_projects(db, scope)}
        if project_id in visible:
            focus_pid = project_id

    if focus_pid is None:
        focus_raw, focus_prev = overall, overall_prev
    else:
        focus_raw = gc.get(focus_pid, dict(_ZERO))
        focus_prev = gp.get(focus_pid, dict(_ZERO))

    metrics = _derive(focus_raw, focus_prev)

    # 按项目下钻明细（含零活动项目，避免遗漏）
    by_project: list[dict] = []
    for pid, name in _accessible_projects(db, scope):
        raw = gc.get(pid, dict(_ZERO))
        prev = gp.get(pid, dict(_ZERO))
        m = _derive(raw, prev)
        score, level = _risk_index(m)
        by_project.append(
            {
                "project_id": pid,
                "project_name": name,
                "risk_index": score,
                "risk_level": level,
                "focused": pid == focus_pid,
                **m,
            }
        )
    # 风险分降序（最需关注的项目在前）
    by_project.sort(key=lambda x: x["risk_index"], reverse=True)

    # 时间序列 sparkline：窗口按桶聚合（桶步长随窗口长度自适应，~30 点），
    # 聚焦项目时序列仅含该项目，否则为全量聚合。
    bucket_days = max(1, round(days / 30))
    series = _collect_time_series(db, scope, start, end, bucket_days, focus_pid)

    return {
        "days": days,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "prev_range_start": prev_start.isoformat(),
        "prev_range_end": prev_end.isoformat(),
        "project_focus": focus_pid,
        "storm": metrics["storm"],
        "mttr": metrics["mttr"],
        "dispatch_sla": metrics["dispatch_sla"],
        "hazard": metrics["hazard"],
        "anomaly": metrics["anomaly"],
        "by_project": by_project,
        "series": series,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def collect_project_series(
    db,
    scope: DataScope,
    days: int,
    project_ids: list[int],
) -> dict[int, dict[str, list[float]]]:
    """按项目聚合时间序列（导出运营报告生成项目级迷你趋势图用）。

    返回 ``{project_id: {metric: [v, v, ...]}}``，每项目 5 指标各一个
    时间桶值列表（无 ``t`` 字段，前端 PNG 渲染不需要时间锚）。

    每个项目调用一次 ``_collect_time_series``（4 次查询）。项目数量一般
    < 20，单次导出 80 次以内查询可接受；如未来项目数膨胀，可改为
    ``GROUP BY (project_id, bucket_index)`` 单查询聚合。
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    bucket_days = max(1, round(days / 30))
    out: dict[int, dict[str, list[float]]] = {}
    for pid in project_ids:
        s = _collect_time_series(db, scope, start, end, bucket_days, pid)
        out[pid] = {k: [pt["v"] for pt in pts] for k, pts in s.items()}
    return out


def project_series_image(
    db,
    scope: DataScope,
    project_id: int,
    days: int = 30,
    width: int = 720,
    height: int = 220,
) -> bytes | None:
    """生成单项目 5 指标复合趋势大图（PNG 字节）。

    复用 compute_effectiveness 的窗口与桶聚合口径（_range + _collect_time_series），
    与效能看板 sparkline / 导出迷你图同源，保证视觉与数值一致。
    项目不可见或无数据时返回 None（端点据此返回 404，避免越权泄露）。
    """
    from app.service import report_common

    start, end = _range(days)
    bucket_days = max(1, round(days / 30))
    s = _collect_time_series(db, scope, start, end, bucket_days, project_id)
    ser = {k: [pt["v"] for pt in pts] for k, pts in s.items()}
    # 全序列均为 0（窗口内该项目无告警/派单/隐患活动）→ 视为无数据，返回 None
    if not ser or not any(any(x != 0 for x in v) for v in ser.values()):
        return None
    return report_common.render_composite_sparkline_png(ser, width=width, height=height)
