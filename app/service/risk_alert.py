"""项目风险指数阈值预警（智能核心 v2 · 阈值预警）。

评估各项目最新风险快照是否越过 ``settings.risk_alert_threshold``，并在「上升沿」
（上一条快照未越阈 / 首次出现）或「同一越阈快照尚未预警过」时，经
``notify_for_project`` 向项目数据范围内的用户下发站内信（category=risk_alert），
实现**可预警 + 可降噪**。

同时维护 Prometheus gauge ``PROJECT_RISK_INDEX``（供 Grafana 阈值告警 / 看板）。
注意：定时快照任务运行在独立 systemd 进程，其进程内 gauge 不会反映到对外暴露的
``/metrics``，因此该 gauge 须在 API 进程内由 ``app/main.py`` 的 ``/metrics`` 钩子
按 DB 最新快照刷新（见 ``refresh_risk_gauges``）。
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.core.metrics import PROJECT_RISK_INDEX
from app.core.notify import notify_for_project
from app.model.risk_alert import RiskAlertState
from app.model.snapshot import RiskHealthSnapshot
from app.service import metrics_snapshot as snap_svc


def _latest_two(db) -> tuple[dict[str, RiskHealthSnapshot], dict[str, RiskHealthSnapshot]]:
    """每个 ref_id 取最新两条项目风险快照（latest, prev），用于上升沿判定。

    返回两个以 ``ref_id`` 为键的字典：``latest`` 为最新一条，``prev`` 为次新一条
    （不存在则为空）。直接遍历按 (ref_id, snapshot_at desc) 排序的全部项目快照，
    在 Python 侧去重，避免逐项目 N+1 查询。
    """
    rows = (
        db.execute(
            select(RiskHealthSnapshot)
            .where(RiskHealthSnapshot.scope_type == "project")
            .order_by(
                RiskHealthSnapshot.ref_id.asc(),
                RiskHealthSnapshot.snapshot_at.desc(),
            )
        )
        .scalars()
        .all()
    )
    latest: dict[str, RiskHealthSnapshot] = {}
    prev: dict[str, RiskHealthSnapshot] = {}
    for r in rows:
        if r.ref_id not in latest:
            latest[r.ref_id] = r
        elif r.ref_id not in prev:
            prev[r.ref_id] = r
    return latest, prev


def refresh_risk_gauges(db) -> None:
    """从最新风险快照刷新 ``PROJECT_RISK_INDEX`` gauge（须在 API 进程内调用）。

    每次全量 clear + set，避免已删除 / 更名项目残留旧序列。任何异常静默，
    绝不阻断 ``/metrics`` 抓取。
    """
    try:
        PROJECT_RISK_INDEX.clear()
        for s in snap_svc.get_latest_risk_snapshots(db):
            idx = s.get("risk_index")
            if idx is None:
                continue
            PROJECT_RISK_INDEX.labels(
                project_id=str(s["project_id"]),
                project_name=s.get("name") or f"p{s['project_id']}",
            ).set(idx)
    except Exception:  # noqa: BLE001
        pass


def evaluate_risk_alerts(db, threshold: int | None = None) -> list[dict]:
    """评估各项目风险越阈情况，返回越阈列表（按风险指数降序）。

    每个越阈项含 ``is_new``（上升沿：上一条快照未越阈或首次出现），供前端标记
    「新预警」；同时刷新 Prometheus gauge。

    说明：``is_new`` 仅用于前端展示语义，真正的「不重复轰炸」由 ``alert_newly_breached``
    基于 ``RiskAlertState`` 去重保证（见该函数）。
    """
    threshold = settings.risk_alert_threshold if threshold is None else threshold
    latest, prev = _latest_two(db)

    breached: list[dict] = []
    for ref_id, snap in latest.items():
        if snap.risk_index is None:
            continue
        idx = snap.risk_index
        is_breach = idx >= threshold
        if not is_breach:
            continue
        prev_snap = prev.get(ref_id)
        prev_breach = (
            prev_snap is not None
            and prev_snap.risk_index is not None
            and prev_snap.risk_index >= threshold
        )
        is_new = not prev_breach
        breached.append(
            {
                "project_id": int(ref_id),
                "name": snap.name,
                "risk_index": idx,
                "risk_level": snap.risk_level,
                "is_new": is_new,
                "threshold": threshold,
                "snapshot_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
            }
        )

    # 始终按最新快照刷新 gauge（供 Grafana / 看板）
    refresh_risk_gauges(db)
    breached.sort(key=lambda x: -x["risk_index"])
    return breached


def alert_newly_breached(db, threshold: int | None = None) -> int:
    """对「当前越阈且尚未为本快照预警过」的项目下发站内信预警（降噪）。

    判定逻辑：
    - 当前快照 ``risk_index >= threshold`` 视为越阈；
    - 若 ``RiskAlertState`` 记录的最近预警快照 == 当前快照（同一快照已预警过）→
      跳过，避免定时任务重跑 / 手动重复触发对同一越阈快照重复轰炸；
    - 否则经 ``notify_for_project`` 下发站内信，并把 ``last_alerted_at`` 更新为
      当前快照时刻（无论是否有人接收，均标记已处理，避免空转重试）。

    返回实际触发下发通知的项目数（0 表示无新增预警）。
    """
    threshold = settings.risk_alert_threshold if threshold is None else threshold
    latest, _ = _latest_two(db)

    sent = 0
    dirty = False
    for ref_id, snap in latest.items():
        if snap.risk_index is None or snap.risk_index < threshold:
            continue
        pid = int(ref_id)
        state = db.scalar(select(RiskAlertState).where(RiskAlertState.project_id == pid))
        if (
            state is not None
            and state.last_alerted_at is not None
            and snap.snapshot_at is not None
            and state.last_alerted_at == snap.snapshot_at
        ):
            # 同一快照已预警过 → 跳过（降噪）
            continue

        title = f"风险预警：{snap.name or f'项目{pid}'} 风险指数 {snap.risk_index}（≥{threshold}）"
        content = (
            f"项目「{snap.name or pid}」最新风险指数 {snap.risk_index}，"
            f"风险等级 {snap.risk_level or '未知'}，已超过阈值 {threshold}。"
            f"请关注项目安全态势，及时排查未处理告警与超期隐患。"
        )
        n = notify_for_project(
            db,
            pid,
            title,
            content=content,
            link="/dashboard/project-compare",
            category="risk_alert",
            channels=("in_app",),
        )

        if state is None:
            state = RiskAlertState(project_id=pid)
            db.add(state)
        state.last_alerted_at = snap.snapshot_at
        state.last_risk_index = snap.risk_index
        dirty = True
        if n > 0:
            sent += 1

    if dirty:
        db.commit()
    return sent
