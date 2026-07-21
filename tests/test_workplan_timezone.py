"""WorkPlan 时间窗时区治理（#11 深化）验证。

依赖本地已执行 alembic upgrade head（plan_start/plan_end 已是 timestamptz）。
覆盖：
- naive 北京墙钟写入 → 读回为 aware 北京（offset +8，墙钟值不变）
- is_plan_active_now 同时兼容 naive / aware 的 plan_start/end 与 now
"""

from datetime import datetime, timedelta

from sqlalchemy import delete

from app.core.clock import now_local
from app.core.database import SessionLocal
from app.core.rule_engine_v2 import is_plan_active_now
from app.model.job import WorkPlan
from app.model.project import Project


def _fake_plan(is_start, status, ps, pe):
    class _P:
        pass

    p = _P()
    p.is_start = is_start
    p.status = status
    p.plan_start = ps
    p.plan_end = pe
    return p


def test_workplan_plan_start_stored_as_beijing_aware():
    db = SessionLocal()
    try:
        proj = Project(name="TZ项目", status="在建")
        db.add(proj)
        db.flush()
        naive_bj = datetime(2026, 1, 1, 10, 0, 0)
        wp = WorkPlan(
            project_id=proj.id,
            name="TZ计划",
            is_start=True,
            status="执行中",
            plan_start=naive_bj,
            plan_end=datetime(2026, 12, 31, 23, 59, 59),
        )
        db.add(wp)
        db.commit()
        db.refresh(wp)
        # 读回应为 aware，且按北京解释（offset +8），墙钟值不变
        assert wp.plan_start is not None
        assert wp.plan_start.utcoffset() == timedelta(hours=8)
        assert wp.plan_start.replace(tzinfo=None) == naive_bj
    finally:
        db.execute(delete(WorkPlan).where(WorkPlan.project_id == proj.id))
        db.execute(delete(Project).where(Project.id == proj.id))
        db.commit()
        db.close()


def test_is_plan_active_now_handles_naive_and_aware():
    now = now_local()
    # 未来开始 → 不激活（aware plan_start）
    assert is_plan_active_now(_fake_plan(True, "执行中", now + timedelta(days=1), None)) is False
    # 当前在闭区间内（naive 北京 plan_start/end，now 为 aware）
    ps = (now - timedelta(hours=1)).replace(tzinfo=None)
    pe = (now + timedelta(hours=1)).replace(tzinfo=None)
    assert is_plan_active_now(_fake_plan(True, "执行中", ps, pe)) is True
    # 已结束
    assert is_plan_active_now(_fake_plan(True, "执行中", ps, now - timedelta(minutes=30))) is False
    # 未启动
    assert is_plan_active_now(_fake_plan(False, "执行中", ps, pe)) is False
    # 非执行中
    assert is_plan_active_now(_fake_plan(True, "草稿", ps, pe)) is False
    # 无时间窗 → 激活
    assert is_plan_active_now(_fake_plan(True, "执行中", None, None)) is True
