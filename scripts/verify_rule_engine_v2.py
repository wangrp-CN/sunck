"""规则引擎 v2 离线自测：纯函数 + SQLite 内存集成（无需 PG/Redis）。

验证要点：
1. parse_plan_rule：结构化解析 + 兼容旧 trigger_condition 单数
2. is_plan_active_now：激活/时间窗判定
3. plan_covers_device：设备覆盖判定
4. fence_geometry_contains：围栏几何命中
5. build_alarm_candidates_v2（sqlite 内存集成）：
   - 围栏侵入（定位设备在计划绑定围栏内）→ 候选带 work_plan_id
   - 间距过近（定位设备紧邻计划绑定大机）→ 候选带 work_plan_id
   - 设备自报（大机/列车上报异常状态）→ 候选带 work_plan_id
   - 仅「激活且覆盖该设备」的计划才会产生告警

运行（rail_monitor 目录下，需 .venv）：
    .venv/bin/python scripts/verify_rule_engine_v2.py
"""

import os
import sys
from datetime import datetime

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.model  # noqa: F401  触发全部表注册
from app.model.base import Base
from app.model.project import Project
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanDevice, WorkPlanFence
from app.model.realtime import DeviceLocation
from app.model.alarm import AlarmConfig
from app.core.rule_engine_v2 import (
    build_alarm_candidates_v2,
    is_plan_active_now,
    parse_plan_rule,
    plan_covers_device,
    fence_geometry_contains,
)
from app.core.constants import (
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
)

_FENCE_WKT = (
    "POLYGON(("
    "121.4995 31.2195, 121.5005 31.2195, "
    "121.5005 31.2205, 121.4995 31.2205, "
    "121.4995 31.2195))"
)

_RESULTS = []


def _check(name: str, cond: bool, detail: str = "") -> None:
    _RESULTS.append((name, cond, detail))
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def _build_db():
    engine = create_engine("sqlite://")
    # 离线用 sqlite：关联表继承的 id 主键会触发「复合主键+自增」不支持。
    # 仅在测试内存库中把四个关联表的 id 移出主键（不影响生产 PG 行为）。
    for tname in (
        "work_plan_person",
        "work_plan_machine",
        "work_plan_device",
        "work_plan_fence",
    ):
        t = Base.metadata.tables.get(tname)
        if t is not None and "id" in t.c:
            t.c["id"].primary_key = False
            t.c["id"].nullable = True
    Base.metadata.create_all(
        engine,
        tables=[
            Project.__table__,
            ElectronicFence.__table__,
            WorkPlan.__table__,
            WorkPlanDevice.__table__,
            WorkPlanFence.__table__,
            DeviceLocation.__table__,
            AlarmConfig.__table__,
        ],
    )
    db = Session(engine)
    proj = Project(name="T", dept_id=None, status="在建")
    db.add(proj)
    db.flush()
    fence = ElectronicFence(project_id=proj.id, name="F1", enabled=True, geometry_wkt=_FENCE_WKT)
    db.add(fence)
    db.flush()
    plan = WorkPlan(
        project_id=proj.id,
        name="P1",
        is_start=True,
        status="执行中",
        plan_start=datetime(2026, 1, 1),
        plan_end=datetime(2027, 12, 31),
        rule_json='{"monitor_target":"person","trigger_conditions":'
        '["fence_intrusion","distance_too_close","device_alarm"],'
        '"time_range":"全天","dwell_time":0}',
    )
    db.add(plan)
    db.flush()
    db.add(WorkPlanDevice(plan_id=plan.id, device_type="locate", device_no="LOC-001"))
    db.add(WorkPlanDevice(plan_id=plan.id, device_type="anti_intrusion", device_no="AI-001"))
    db.add(WorkPlanFence(plan_id=plan.id, fence_id=fence.id))
    # 参考大机最新位置（紧邻围栏西侧）
    db.add(
        DeviceLocation(
            device_type="anti_intrusion",
            device_no="AI-001",
            device_name="大机-A",
            project_id=proj.id,
            longitude=121.4996,
            latitude=31.2200,
            status="在线",
            report_time=datetime(2026, 7, 15),
        )
    )
    db.commit()
    return db, plan.id, proj.id


def test_pure():
    print("纯函数测试：")
    # parse_plan_rule
    r = parse_plan_rule('{"trigger_condition":"fence_intrusion","dwell_time":"30"}')
    _check("parse 旧单数 trigger_condition→list", r["trigger_conditions"] == ["fence_intrusion"])
    _check("parse dwell_time 转 int", r["dwell_time"] == 30)
    r2 = parse_plan_rule(None)
    _check("parse None→全 None", r2["trigger_conditions"] is None)
    r3 = parse_plan_rule('{"trigger_conditions":["fence_intrusion","device_alarm"]}')
    _check("parse 新 list 保留", r3["trigger_conditions"] == ["fence_intrusion", "device_alarm"])

    # is_plan_active_now
    class P:
        is_start = True
        status = "执行中"
        plan_start = None
        plan_end = None

    _check("active 基础 True", is_plan_active_now(P()))
    past = P()
    past.plan_end = datetime(2020, 1, 1)
    _check("active 时间窗过期→False", not is_plan_active_now(past))
    future = P()
    future.plan_start = datetime(2030, 1, 1)
    _check("active 未开始→False", not is_plan_active_now(future))
    off = P()
    off.is_start = False
    _check("active is_start=False→False", not is_plan_active_now(off))

    # plan_covers_device
    _check("覆盖 空绑定=全覆盖", plan_covers_device([], "LOC-001"))
    _check("覆盖 命中", plan_covers_device(["LOC-001", "AI-001"], "LOC-001"))
    _check("覆盖 未命中", not plan_covers_device(["LOC-001"], "TA-001"))

    # fence_geometry_contains
    class F:
        name = "F1"
        geometry_wkt = _FENCE_WKT

    _check("围栏 内点命中", fence_geometry_contains(F(), 121.5000, 31.2200))
    _check("围栏 外点不命中", not fence_geometry_contains(F(), 121.5030, 31.2200))


def test_integration():
    print("集成测试（sqlite 内存）：")
    db, plan_id, proj_id = _build_db()
    now = datetime(2026, 7, 15)

    # A) 围栏侵入：定位设备在围栏中心，且计划绑定该围栏
    parsed_in = {
        "device_no": "LOC-001",
        "longitude": 121.5000,
        "latitude": 31.2200,
        "report_time": now,
    }
    cands = build_alarm_candidates_v2(
        db,
        device_type="locate",
        device_no="LOC-001",
        device_name="张三",
        project_id=proj_id,
        parsed=parsed_in,
        location=None,
    )
    fence_hits = [c for c in cands if c["alarm_type"] == ALARM_TYPE_FENCE]
    _check("围栏侵入产生候选", len(fence_hits) == 1, f"count={len(fence_hits)}")
    if fence_hits:
        _check("围栏候选带 work_plan_id", fence_hits[0].get("work_plan_id") == plan_id)

    # B) 间距过近：定位设备与大机同点
    parsed_dist = {
        "device_no": "LOC-001",
        "longitude": 121.4996,
        "latitude": 31.2200,
        "report_time": now,
    }
    cands2 = build_alarm_candidates_v2(
        db,
        device_type="locate",
        device_no="LOC-001",
        device_name="张三",
        project_id=proj_id,
        parsed=parsed_dist,
        location=None,
    )
    dist_hits = [c for c in cands2 if c["alarm_type"] == ALARM_TYPE_DISTANCE]
    _check("间距过近产生候选", len(dist_hits) == 1, f"count={len(dist_hits)}")
    if dist_hits:
        _check("间距候选带 work_plan_id", dist_hits[0].get("work_plan_id") == plan_id)

    # C) 设备自报：大机上报异常状态
    parsed_dev = {
        "device_no": "AI-001",
        "alarm_status": "告警",
        "alarm_info": "大机异常",
        "report_time": now,
    }
    cands3 = build_alarm_candidates_v2(
        db,
        device_type="anti_intrusion",
        device_no="AI-001",
        device_name="大机-A",
        project_id=proj_id,
        parsed=parsed_dev,
        location=None,
    )
    dev_hits = [c for c in cands3 if c["alarm_type"] == ALARM_TYPE_DEVICE]
    _check("设备自报产生候选", len(dev_hits) == 1, f"count={len(dev_hits)}")
    if dev_hits:
        _check("设备候选带 work_plan_id", dev_hits[0].get("work_plan_id") == plan_id)

    # D) 未覆盖的设备（TA 未绑定计划）→ 不应产生告警
    parsed_ta = {
        "device_no": "TA-999",
        "alarm_status": "告警",
        "alarm_info": "列车异常",
        "report_time": now,
    }
    cands4 = build_alarm_candidates_v2(
        db,
        device_type="train_approach",
        device_no="TA-999",
        device_name="列车-X",
        project_id=proj_id,
        parsed=parsed_ta,
        location=None,
    )
    _check("未覆盖设备不产生告警", len(cands4) == 0, f"count={len(cands4)}")

    db.close()


def main():
    test_pure()
    print()
    test_integration()
    print()
    failed = [r for r in _RESULTS if not r[1]]
    print(f"总计 {len(_RESULTS)} 项，失败 {len(failed)} 项。")
    if failed:
        for name, _, detail in failed:
            print(f"  FAIL: {name} {detail}")
        sys.exit(1)
    print("全部通过 ✅")


if __name__ == "__main__":
    main()
