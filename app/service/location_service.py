"""实时定位服务：落库设备上报坐标 + 查询最新位置（地图打点/轨迹回放）。"""

from datetime import datetime

from sqlalchemy import func, select

from app.model.realtime import DeviceLocation


def save_location(
    db,
    *,
    device_type: str,
    device_no: str,
    device_name: str | None = None,
    project_id: int | None = None,
    longitude: float | None = None,
    latitude: float | None = None,
    altitude: float | None = None,
    accuracy: float | None = None,
    speed: float | None = None,
    bearing: float | None = None,
    status: str = "在线",
    report_time: datetime | None = None,
    raw_payload: str | None = None,
) -> DeviceLocation:
    """写入一条实时定位记录（时序表，高频）。"""
    loc = DeviceLocation(
        device_type=device_type,
        device_no=device_no,
        device_name=device_name,
        project_id=project_id,
        longitude=longitude,
        latitude=latitude,
        altitude=altitude,
        accuracy=accuracy,
        speed=speed,
        bearing=bearing,
        status=status,
        report_time=report_time,
        raw_payload=raw_payload,
    )
    db.add(loc)
    db.flush()
    return loc


def latest_locations(
    db,
    project_id: int | None = None,
    device_type: str | None = None,
    limit: int = 2000,
) -> list[DeviceLocation]:
    """返回每个设备的最新一条位置（按 device_no 分组取最大 id）。

    实现：先经 ``GROUP BY device_no`` 取各设备 ``max(id)``（利用
    ``ix_device_location_device_id (device_no, id)`` 索引做窄索引聚合，
    仅读索引、不触达宽行、不产生全表/全排序），再按主键回表取完整行。
    复杂度与设备数成正比（而非与 device_location 时序表总行数成正比），
    根治既往 ``DISTINCT ON`` 在高频大表上「扫数万行 + 排序溢写磁盘」的瓶颈。
    """
    subq = select(func.max(DeviceLocation.id).label("max_id"))
    if project_id is not None:
        subq = subq.where(DeviceLocation.project_id == project_id)
    if device_type is not None:
        subq = subq.where(DeviceLocation.device_type == device_type)
    subq = subq.group_by(DeviceLocation.device_no).subquery()
    stmt = (
        select(DeviceLocation)
        .join(subq, DeviceLocation.id == subq.c.max_id)
        .order_by(DeviceLocation.device_no)
    )
    return db.scalars(stmt.limit(limit)).all()


def trajectory(
    db,
    *,
    device_no: str,
    start: datetime,
    end: datetime,
    project_id: int | None = None,
    limit: int = 5000,
) -> list[DeviceLocation]:
    """返回单设备在某时间段内的有序位置序列（轨迹回放）。

    利用 `(device_no, report_time)` 复合索引，按时间升序返回。
    """
    stmt = select(DeviceLocation).where(
        DeviceLocation.device_no == device_no,
        DeviceLocation.report_time >= start,
        DeviceLocation.report_time <= end,
    )
    if project_id is not None:
        stmt = stmt.where(DeviceLocation.project_id == project_id)
    stmt = stmt.order_by(DeviceLocation.report_time.asc())
    return db.scalars(stmt.limit(limit)).all()
