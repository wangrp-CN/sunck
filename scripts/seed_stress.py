"""阶段3 压测专用种子脚本：批量登记「千台设备」用于 ingestion 链路压测。

设计要点：
- 创建独立 stress 项目（name=压测专用-STRESS），与演示数据隔离；
- 批量登记 N 台 locate 设备（LOC-S00001..LOC-SNNNNN），绑定该项目；
- 幂等：运行前先按前缀 / 名称清理历史 stress 数据；
- 无激活作业计划 → pipeline 不产生告警风暴，仅落库 DeviceLocation，
  从而隔离出「千台设备位置上报」这一 ingestion 链路的真实压力。

用法（rail_monitor 目录下，需处于已装依赖的 venv）：
    .venv/bin/python scripts/seed_stress.py            # 登记 STRESS_N 台（默认 1000）
    .venv/bin/python scripts/seed_stress.py clean      # 仅清理
    STRESS_N=2000 .venv/bin/python scripts/seed_stress.py
"""

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sqlalchemy import delete  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.model.device import LocateDevice  # noqa: E402
from app.model.project import Project  # noqa: E402
from app.model.realtime import DeviceLocation  # noqa: E402

STRESS_NAME = "压测专用-STRESS"
DEVICE_PREFIX = "LOC-S"
N_DEVICES = int(os.getenv("STRESS_N", "1000"))


def _clean(db) -> None:
    # 时序位置表（高频写入）先于配置表清理，避免悬空行堆积
    db.execute(delete(DeviceLocation).where(DeviceLocation.device_no.like(f"{DEVICE_PREFIX}%")))
    db.execute(delete(LocateDevice).where(LocateDevice.device_no.like(f"{DEVICE_PREFIX}%")))
    db.execute(delete(Project).where(Project.name == STRESS_NAME))
    db.commit()


def seed(n: int) -> int:
    db = SessionLocal()
    try:
        _clean(db)
        proj = Project(
            name=STRESS_NAME, short_name="STRESS", status="在建", intro="Locust 压测专用项目"
        )
        db.add(proj)
        db.flush()
        pid = proj.id
        objs = [
            LocateDevice(
                project_id=pid,
                name=f"压测设备{i:05d}",
                device_no=f"{DEVICE_PREFIX}{i:05d}",
                device_type="locate",
                function="实时定位",
                status="在线",
            )
            for i in range(1, n + 1)
        ]
        db.bulk_save_objects(objs)
        db.commit()
        print(f"SEEDED project_id={pid} devices={n}")
        return pid
    finally:
        db.close()


def clean_only() -> None:
    db = SessionLocal()
    try:
        _clean(db)
        print("CLEANED stress data")
    finally:
        db.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "seed"
    if cmd == "clean":
        clean_only()
    else:
        seed(N_DEVICES)
