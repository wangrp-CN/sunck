"""阶段1 演示数据播种：演示项目 + 三类设备 + 电子围栏 + 告警配置。

幂等：按 项目名 / 设备编号 存在性跳过。

坐标均为 WGS-84（与设备上报一致）；围栏多边形围绕定位设备巡逻区，
模拟器会让定位设备逐步「侵入」围栏以触发告警（验证 M1 ②）。

用法（rail_monitor 目录下）：
    .venv/bin/python scripts/seed_demo.py
"""

import os
import sys
import json
from datetime import datetime

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from sqlalchemy import select

from app.core.constants import (
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.core.database import SessionLocal
from app.model.alarm import AlarmConfig
from app.model.device import AntiIntrusionDevice, LocateDevice, TrainApproachDevice
from app.model.fence import ElectronicFence
from app.model.job import WorkPlan, WorkPlanDevice, WorkPlanFence
from app.model.project import Project

# 演示项目
_DEMO_PROJECT_NAME = "沪昆铁路 K123+500 涉铁施工段"
_DEPT_CODE = "SECTION"  # 归属工务段（与数据隔离演示一致）

# 演示作业计划（激活，使规则引擎 v2 据此产生告警并溯源）
_DEMO_PLAN_NAME = "K123+500 夜间施工安全监护"

# 围栏中心（WGS-84）与多边形（约 ±50m）
_FENCE_CENTER = (121.5000, 31.2200)
_FENCE_WKT = (
    "POLYGON(("
    "121.4995 31.2195, "
    "121.5005 31.2195, "
    "121.5005 31.2205, "
    "121.4995 31.2205, "
    "121.4995 31.2195))"
)

# 设备（编号 / 名称 / 配置坐标）
_LOCATE = ("LOC-001", "张三定位工牌", 121.5030, 31.2200)  # 起点在围栏东侧(外)
_AI = ("AI-001", "大机防侵限-A", 121.4996, 31.2200)  # 紧邻围栏西侧(用于间距演示)
_TA = ("TA-001", "列车接近-上行", 121.5010, 31.2210)  # 围栏东北侧


def _get_dept_id(db, code: str) -> int | None:
    from app.model.system import Department

    return db.scalar(select(Department.id).where(Department.code == code))


def seed_demo(db=None) -> dict:
    own = db is None
    if own:
        db = SessionLocal()
    stats = {"project": 0, "devices": 0, "fence": 0, "alarm_config": 0, "work_plan": 0}
    try:
        dept_id = _get_dept_id(db, _DEPT_CODE)
        # 1) 项目
        project = db.scalar(select(Project).where(Project.name == _DEMO_PROJECT_NAME))
        if project is None:
            project = Project(
                name=_DEMO_PROJECT_NAME,
                dept_id=dept_id,
                short_name="K123+500",
                section="沪昆线 K123+300~K123+700",
                mileage="K123+500",
                coordinate=f"{_FENCE_CENTER[0]},{_FENCE_CENTER[1]}",
                status="在建",
            )
            db.add(project)
            db.flush()
            stats["project"] += 1
        pid = project.id

        # 2) 三类设备
        def _ensure_device(model, device_no, name, lng=None, lat=None, **extra):
            row = db.scalar(select(model).where(model.device_no == device_no))
            if row is None:
                kwargs = dict(
                    device_no=device_no,
                    name=name,
                    project_id=pid,
                    status="在线",
                    **extra,
                )
                if lng is not None:
                    kwargs["longitude"] = lng
                if lat is not None:
                    kwargs["latitude"] = lat
                row = model(**kwargs)
                db.add(row)
                db.flush()
                stats["devices"] += 1
            return row

        _ensure_device(
            LocateDevice, _LOCATE[0], _LOCATE[1], device_type="人员手持机", function="人员实时定位"
        )
        _ensure_device(AntiIntrusionDevice, _AI[0], _AI[1], _AI[2], _AI[3])
        _ensure_device(TrainApproachDevice, _TA[0], _TA[1], _TA[2], _TA[3], direction="上行")

        # 3) 电子围栏
        fence = db.scalar(
            select(ElectronicFence).where(
                ElectronicFence.name == "K123+500 人员禁区",
                ElectronicFence.project_id == pid,
            )
        )
        if fence is None:
            fence = ElectronicFence(
                project_id=pid,
                name="K123+500 人员禁区",
                fence_type="人员禁区",
                enabled=True,
                geometry_wkt=_FENCE_WKT,
            )
            db.add(fence)
            stats["fence"] += 1

        # 4) 告警配置（间距阈值）
        if db.scalar(select(AlarmConfig)) is None:
            db.add(
                AlarmConfig(
                    enable_popup=True,
                    enable_voice=True,
                    distance_machine=50,
                    distance_handheld=20,
                    distance_badge=20,
                    distance_band=20,
                )
            )
            stats["alarm_config"] += 1

        # 5) 演示作业计划（激活中，绑定三设备+围栏，全触发条件，宽时间窗）
        stats["work_plan"] = seed_active_plan(db, pid, fence)

        db.commit()
        return stats
    finally:
        if own:
            db.close()


def seed_active_plan(db, project_id: int, fence) -> int:
    """创建/补充演示激活作业计划；返回新增计划数（0 表示已存在）。"""
    from app.model.system import User

    plan = db.scalar(
        select(WorkPlan).where(WorkPlan.name == _DEMO_PLAN_NAME, WorkPlan.project_id == project_id)
    )
    added = 0
    if plan is None:
        admin = db.scalar(select(User).where(User.username == "admin"))
        plan = WorkPlan(
            project_id=project_id,
            name=_DEMO_PLAN_NAME,
            is_start=True,
            status="执行中",
            description="K123+500 夜间施工安全监护（演示激活计划）",
            plan_start=datetime(2026, 1, 1),
            plan_end=datetime(2027, 12, 31),
            rule_json=json.dumps(
                {
                    "monitor_target": "person",
                    "trigger_conditions": [
                        "fence_intrusion",
                        "distance_too_close",
                        "device_alarm",
                    ],
                    "time_range": "全天",
                    "dwell_time": 0,
                },
                ensure_ascii=False,
            ),
            created_by=admin.id if admin else None,
        )
        db.add(plan)
        db.flush()
        added = 1
    pid_val = plan.id
    # 绑定三类设备（按 device_type + device_no）
    bound = {
        (DEVICE_TYPE_LOCATE, _LOCATE[0]),
        (DEVICE_TYPE_ANTI_INTRUSION, _AI[0]),
        (DEVICE_TYPE_TRAIN_APPROACH, _TA[0]),
    }
    existing = set(
        db.scalars(
            select(WorkPlanDevice.device_type, WorkPlanDevice.device_no).where(
                WorkPlanDevice.plan_id == pid_val
            )
        ).all()
    )
    for dtype, dno in bound - existing:
        db.add(WorkPlanDevice(plan_id=pid_val, device_type=dtype, device_no=dno))
    if (fence.id,) not in set(
        db.scalars(select(WorkPlanFence.fence_id).where(WorkPlanFence.plan_id == pid_val)).all()
    ):
        db.add(WorkPlanFence(plan_id=pid_val, fence_id=fence.id))
    return added


if __name__ == "__main__":
    print("阶段1 演示数据播种：")
    s = seed_demo()
    print(
        f"  新增项目：{s['project']}  设备：{s['devices']}  围栏：{s['fence']}  告警配置：{s['alarm_config']}  作业计划：{s['work_plan']}"
    )
    print(f"  演示项目：{_DEMO_PROJECT_NAME}")
    print(f"  演示激活作业计划：{_DEMO_PLAN_NAME}（绑定三设备+围栏，规则引擎 v2 据其产生告警）")
    print(
        f"  定位设备 {_LOCATE[0]} 起点({_LOCATE[2]},{_LOCATE[3]}) → 围栏中心({_FENCE_CENTER[0]},{_FENCE_CENTER[1]})"
    )
