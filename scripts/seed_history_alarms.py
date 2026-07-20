"""阶段1b 跨周期历史告警播种：让告警趋势图（按周/月聚合）能渲染多个桶，自证多周期聚合与轴标签。

幂等：每次运行先 DELETE 标记 HIST_SEED 的历史告警，再重新插入，结果稳定、可重复运行。
不依赖实时模拟器；可与 run_demo.sh 的 [3.5b] 步骤配合，在清空 alarm 表之后、后端启动之前注入，
使演示环境重启后趋势图（周/月）即可见多个周期桶。

用法（rail_monitor 目录下）：
    .venv/bin/python scripts/seed_history_alarms.py
"""

import calendar
import os
import sys
from datetime import datetime, timezone

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
_SCRIPTS = os.path.join(_PROJECT_ROOT, "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from sqlalchemy import delete, select

from app.core.constants import (
    ALARM_STATUS_START,
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    DEVICE_TYPE_ANTI_INTRUSION,
    DEVICE_TYPE_LOCATE,
    DEVICE_TYPE_TRAIN_APPROACH,
)
from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.job import WorkPlan
from app.model.project import Project
from seed_demo import seed_demo, _DEMO_PLAN_NAME, _DEMO_PROJECT_NAME

_HIST_MARK = "HIST_SEED"

# (告警类型, 级别, 设备类型, 设备编号, 设备名称, 围栏名)
_TYPE_SPECS = [
    (ALARM_TYPE_FENCE, "严重", DEVICE_TYPE_LOCATE, "LOC-001", "张三定位工牌", "K123+500 人员禁区"),
    (ALARM_TYPE_DISTANCE, "警告", DEVICE_TYPE_ANTI_INTRUSION, "AI-001", "大机防侵限-A", None),
    (ALARM_TYPE_DEVICE, "提示", DEVICE_TYPE_TRAIN_APPROACH, "TA-001", "列车接近-上行", None),
]
_HANDLE_STATUSES = ["待处理", "已处理", "已忽略", "已确认"]


def seed_history_alarms(db=None) -> int:
    """插入跨多个周/月的历史告警，返回新增条数。幂等（先清 HIST_SEED 再插）。"""
    own = db is None
    if own:
        db = SessionLocal()
    total = 0
    try:
        # 确保基础演示数据（项目 + 激活作业计划）存在且最新
        seed_demo(db)
        project = db.scalar(select(Project).where(Project.name == _DEMO_PROJECT_NAME))
        plan = db.scalar(
            select(WorkPlan).where(
                WorkPlan.name == _DEMO_PLAN_NAME,
                WorkPlan.project_id == project.id,
            )
        )
        pid = project.id
        plan_id = plan.id if plan else None

        # 清旧历史，保证幂等
        db.execute(delete(Alarm).where(Alarm.alarm_info.like(f"{_HIST_MARK}%")))

        # 跨 3 个月确定性播种（05 全月 / 06 全月 / 07 上半月）
        spans = [(2026, 5, 1, 31), (2026, 6, 1, 30), (2026, 7, 1, 15)]
        for y, m, d0, d1 in spans:
            for day in range(d0, d1 + 1):
                # 当日条数：确定性（1~6），让各月量级有差异
                n = (day * 7 + m * 3) % 6 + 1
                for k in range(n):
                    t_idx = (day + k) % 3
                    atype, level, dtype, dno, dname, fence = _TYPE_SPECS[t_idx]
                    hour = 8 + ((day + k * 3) % 12)  # 本地 8~19 → UTC 同日内，绝不跨日
                    minute = (k * 17) % 60
                    at = datetime(y, m, day, hour, minute, 0, tzinfo=timezone.utc)
                    db.add(
                        Alarm(
                            project_id=pid,
                            work_plan_id=plan_id,
                            alarm_type=atype,
                            device_type=dtype,
                            device_name=dname,
                            device_no=dno,
                            alarm_info=f"{_HIST_MARK} {y}-{m:02d}-{day:02d}",
                            alarm_status=ALARM_STATUS_START,
                            alarm_level=level,
                            handle_status=_HANDLE_STATUSES[(day + k) % 4],
                            alarm_time=at,
                            fence_name=fence,
                        )
                    )
                    total += 1
        db.commit()
        return total
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    # 手动单独运行时，确保 RBAC 与基础演示数据已就位
    try:
        from seed_rbac import seed_rbac

        seed_rbac()
    except Exception as e:  # noqa: BLE001
        print(f"（跳过 RBAC 播种：{e}，若已存在可忽略）")
    print("阶段1b 跨周期历史告警播种：")
    n = seed_history_alarms()
    print(f"  新增历史告警：{n} 条（跨 2026-05 / 2026-06 / 2026-07 多周多月）")
    print(f"  标记：{_HIST_MARK}%（幂等，重复运行结果一致）")
