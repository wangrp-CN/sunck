"""风险健康报表生成器（Phase 1 报表导出）。

基于 ``risk_health_snapshot`` 分时序快照表，聚合出「风险健康日报/周报」：

- 日报 = 昨日（本地时区零点对齐）；周报 = 上周（周一~周日，本地时区）；
- 项目风险：每项目周期内最新风险分 + 相对上一周期的环比 Δ；
- 设备健康：周期内最新健康分/等级/在线状态分布 + 平均健康分；
- Top 风险项目 / Top 亚健康设备 速览。

数据范围复用 ``DataScope``：项目快照按 ``ref_id = str(project_id)`` 过滤，
设备快照按「允许项目 → 设备编号集合」过滤（与全站部门隔离口径一致）。
报告拼装复用 ``app.service.report_common`` 的 ``build_simple_excel/build_simple_pdf``，
与效能运营报告同源、对称。

返回 ``(content: bytes, filename: str, media_type: str)``，调用方自行决定
StreamingResponse 直出或落库/触达。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from app.core.clock import LOCAL_TZ
from app.core.data_scope import DataScope
from app.core.exceptions import BusinessError
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.project import Project
from app.model.snapshot import RiskHealthSnapshot
from app.service.report_common import build_simple_excel, build_simple_pdf

DEVICE_MODELS = [AntiIntrusionDevice, LocateDevice, TrainApproachDevice]

HEALTH_LABELS = ["优", "良", "中", "差"]
ONLINE_LABELS = {"fresh": "在线", "stale": "延迟", "offline": "离线"}


def period_bounds(period_type: str, ref_now: datetime | None = None):
    """返回 ``(start, end, prev_start, prev_end)``，均为本地时区 aware。

    - daily：昨日 ``[today-1d, today)``；
    - weekly：上周 ``[本周一-7d, 本周一)``（周一=0）。
    """
    now = ref_now or datetime.now(LOCAL_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period_type == "weekly":
        this_monday = today - timedelta(days=now.weekday())
        end = this_monday
        start = end - timedelta(days=7)
    else:  # daily
        end = today
        start = end - timedelta(days=1)
    prev_end = start
    prev_start = start - (end - start)
    return start, end, prev_start, prev_end


def _scope_project_ids(db, scope: DataScope) -> set[int] | None:
    """返回可见项目 ID 集合；is_all 或无部门限制返回 None（全部）。"""
    if scope.is_all or not scope.dept_ids:
        return None
    ids = db.scalars(select(Project.id).where(Project.dept_id.in_(scope.dept_ids))).all()
    return set(ids)


def _allowed_device_nos(db, project_ids: set[int] | None) -> set[str] | None:
    """允许项目对应的设备编号集合；project_ids 为 None 表示全部。"""
    if project_ids is None:
        return None
    nos: set[str] = set()
    for m in DEVICE_MODELS:
        rows = db.execute(
            select(m.device_no).where(m.project_id.in_(project_ids), m.is_deleted.is_(False))
        ).all()
        for (no,) in rows:
            nos.add(no)
    return nos


def _fetch_latest_per_ref(db, scope_type: str, ref_ids: set[str] | None, start, end):
    """取 [start, end) 内每个 ref_id 的最新一条快照（Python 端按 snapshot_at 取最大）。"""
    stmt = select(RiskHealthSnapshot).where(
        RiskHealthSnapshot.scope_type == scope_type,
        RiskHealthSnapshot.snapshot_at >= start,
        RiskHealthSnapshot.snapshot_at < end,
    )
    if ref_ids is not None:
        stmt = stmt.where(RiskHealthSnapshot.ref_id.in_(ref_ids))
    rows = db.execute(stmt).scalars().all()
    latest: dict[str, RiskHealthSnapshot] = {}
    for r in rows:
        cur = latest.get(r.ref_id)
        if cur is None or r.snapshot_at > cur.snapshot_at:
            latest[r.ref_id] = r
    return latest


def collect_risk_health_report(
    db, scope: DataScope, period_type: str = "weekly", ref_now: datetime | None = None
) -> dict:
    """聚合风险健康报表数据（JSON 结构，供预览与导出共用）。"""
    if period_type not in ("daily", "weekly"):
        raise BusinessError("period_type 仅支持 daily|weekly", code=400)

    start, end, prev_start, prev_end = period_bounds(period_type, ref_now)
    pids = _scope_project_ids(db, scope)
    proj_ref_ids = None if pids is None else {str(p) for p in pids}
    dev_nos = _allowed_device_nos(db, pids)

    curr_proj = _fetch_latest_per_ref(db, "project", proj_ref_ids, start, end)
    prev_proj = _fetch_latest_per_ref(db, "project", proj_ref_ids, prev_start, prev_end)
    curr_dev = _fetch_latest_per_ref(db, "device", dev_nos, start, end)

    project_rows: list[dict] = []
    for ref_id, snap in curr_proj.items():
        prev = prev_proj.get(ref_id)
        prev_idx = prev.risk_index if prev else None
        delta = (
            snap.risk_index - prev_idx
            if (prev_idx is not None and snap.risk_index is not None)
            else None
        )
        project_rows.append(
            {
                "project_id": int(ref_id),
                "name": snap.name,
                "risk_index": snap.risk_index,
                "risk_level": snap.risk_level,
                "prev_risk_index": prev_idx,
                "delta": delta,
            }
        )
    project_rows.sort(key=lambda x: (x["risk_index"] is None, -(x["risk_index"] or 0)))

    health_dist = {k: 0 for k in HEALTH_LABELS}
    online_dist = {k: 0 for k in ONLINE_LABELS}
    scores: list[int] = []
    device_rows: list[dict] = []
    for ref_id, snap in curr_dev.items():
        if snap.health_level in health_dist:
            health_dist[snap.health_level] += 1
        if snap.online_state in online_dist:
            online_dist[snap.online_state] += 1
        if snap.health_score is not None:
            scores.append(snap.health_score)
        device_rows.append(
            {
                "device_no": ref_id,
                "name": snap.name,
                "health_score": snap.health_score,
                "health_level": snap.health_level,
                "online_state": snap.online_state,
            }
        )
    device_rows.sort(key=lambda x: (x["health_score"] is None, (x["health_score"] or 0)))

    risk_vals = [p["risk_index"] for p in project_rows if p["risk_index"] is not None]
    avg_risk = round(sum(risk_vals) / len(risk_vals), 1) if risk_vals else None
    avg_health = round(sum(scores) / len(scores), 1) if scores else None

    summary = {
        "project_count": len(project_rows),
        "avg_risk": avg_risk,
        "high_risk_count": len([p for p in project_rows if p["risk_level"] == "高"]),
        "device_count": len(device_rows),
        "avg_health": avg_health,
        "offline_count": online_dist["offline"],
        "health_dist": health_dist,
        "online_dist": online_dist,
    }

    period_label = "周报（上周）" if period_type == "weekly" else "日报（昨日）"
    return {
        "period_type": period_type,
        "period_label": period_label,
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "summary": summary,
        "project_rows": project_rows,
        "device_rows": device_rows,
        "top_risky_projects": [p for p in project_rows if p["risk_level"] in ("高", "中")][:5],
        "top_unhealthy_devices": device_rows[:5],
    }


def generate_risk_health_report(
    db, scope: DataScope, *, period_type: str = "weekly", fmt: str = "excel"
) -> tuple[bytes, str, str]:
    """生成风险健康报表（Excel / PDF）。

    Returns:
        ``(content_bytes, filename, media_type)``。
    """
    fmt = (fmt or "excel").lower()
    if fmt not in ("excel", "pdf"):
        raise BusinessError("不支持的导出格式（excel|pdf）", code=400)

    data = collect_risk_health_report(db, scope, period_type)
    s = data["summary"]
    period_label = data["period_label"]
    filters_desc = (
        f"统计周期：{period_label}（{data['range_start'][:10]} ~ {data['range_end'][:10]}）"
    )
    meta = {
        "title": f"风险健康{period_label}报表",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "filters_desc": filters_desc,
    }

    proj_cols: list[tuple[str, str, int, int]] = [
        ("name", "项目", 22, 40),
        ("risk_level", "风险等级", 10, 18),
        ("risk_index", "风险分", 10, 18),
        ("prev_risk_index", "上期风险分", 12, 20),
        ("delta", "环比Δ", 10, 18),
    ]
    proj_rows = [
        {
            "name": p["name"],
            "risk_level": p["risk_level"],
            "risk_index": p["risk_index"],
            "prev_risk_index": p["prev_risk_index"] if p["prev_risk_index"] is not None else "—",
            "delta": (f"{p['delta']:+.0f}" if p["delta"] is not None else "新"),
        }
        for p in data["project_rows"]
    ]

    dev_cols: list[tuple[str, str, int, int]] = [
        ("device_no", "设备编号", 20, 40),
        ("name", "名称", 18, 32),
        ("health_level", "健康等级", 10, 18),
        ("health_score", "健康分", 10, 18),
        ("online_state", "在线状态", 12, 20),
    ]
    dev_rows = [
        {
            "device_no": d["device_no"],
            "name": d["name"],
            "health_level": d["health_level"],
            "health_score": d["health_score"],
            "online_state": ONLINE_LABELS.get(d["online_state"], d["online_state"]),
        }
        for d in data["device_rows"]
    ]

    summary_blocks = [
        (
            "项目概览",
            [
                ("纳入项目数", s["project_count"]),
                ("平均风险分", s["avg_risk"] if s["avg_risk"] is not None else "—"),
                ("高风险项目数", s["high_risk_count"]),
            ],
        ),
        (
            "设备概览",
            [
                ("纳入设备数", s["device_count"]),
                ("平均健康分", s["avg_health"] if s["avg_health"] is not None else "—"),
                ("离线设备数", s["offline_count"]),
                (
                    "健康(优/良/中/差)",
                    f"{s['health_dist']['优']}/{s['health_dist']['良']}/{s['health_dist']['中']}/{s['health_dist']['差']}",
                ),
                (
                    "在线(在线/延迟/离线)",
                    f"{s['online_dist']['fresh']}/{s['online_dist']['stale']}/{s['online_dist']['offline']}",
                ),
            ],
        ),
    ]

    if fmt == "pdf":
        content = build_simple_pdf(
            proj_cols,
            proj_rows,
            meta,
            summary_blocks,
            extra_tables=[("设备健康明细", dev_cols, dev_rows)],
        )
        media_type = "application/pdf"
        filename = f"风险健康报表_{period_type}.pdf"
    else:
        content = build_simple_excel(
            proj_cols,
            proj_rows,
            meta,
            summary_blocks,
            extra_sheets=[("设备健康", dev_cols, dev_rows, None)],
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"风险健康报表_{period_type}.xlsx"

    return content, filename, media_type
