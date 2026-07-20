"""实时链路编排（MQTT 线程内调用）：上行报文 → 落库 → 规则判定 → 产生告警 → WS 推送。

保持与 HTTP 请求路径解耦：任何线程（paho 网络线程）都可安全调用，
内部自开数据库会话，并通过 ws.bridge 跨线程投递 WebSocket 消息。
"""

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.constants import ALARM_STATUS_START, ws_channel_for_project
from app.core.database import SessionLocal
from app.core.geo import wgs84_to_gcj02
from app.core.redis import get_redis_client
from app.core.rule_engine_v2 import build_alarm_candidates_v2
from app.model.realtime import DeviceLocation
from app.service.alarm_service import (
    create_alarm,
    dedup_key,
    reconcile_active_alarms,
    to_alarm_out,
)
from app.service.device_service import resolve_device
from app.service.location_service import save_location
from app.ws import bridge

logger = logging.getLogger("rail_monitor.pipeline")


def _location_to_ws(loc: DeviceLocation) -> dict[str, Any]:
    lng, lat = loc.longitude, loc.latitude
    gcj = None
    if lng is not None and lat is not None:
        glng, glat = wgs84_to_gcj02(lng, lat)
        gcj = {"lng": glng, "lat": glat}
    return {
        "type": "location",
        "data": {
            "device_type": loc.device_type,
            "device_no": loc.device_no,
            "device_name": loc.device_name,
            "project_id": loc.project_id,
            "longitude": lng,
            "latitude": lat,
            "gcj02": gcj,
            "accuracy": loc.accuracy,
            "speed": loc.speed,
            "status": loc.status,
            "report_time": loc.report_time.isoformat() if loc.report_time else None,
        },
    }


def handle_upstream(device_type: str, parsed: dict[str, Any], db: Session | None = None) -> dict:
    """处理一条已解析的上行报文，返回处理摘要。"""
    own = db is None
    if own:
        db = SessionLocal()
    loc: DeviceLocation | None = None
    created_alarms: list = []
    try:
        dev = resolve_device(db, device_type, parsed["device_no"])
        project_id = dev["project_id"] if dev else None
        device_name = (dev or {}).get("name") or parsed["device_no"]

        loc = save_location(
            db,
            device_type=device_type,
            device_no=parsed["device_no"],
            device_name=device_name,
            project_id=project_id,
            longitude=parsed.get("longitude"),
            latitude=parsed.get("latitude"),
            altitude=parsed.get("altitude"),
            accuracy=parsed.get("accuracy"),
            speed=parsed.get("speed"),
            bearing=parsed.get("bearing"),
            status=parsed.get("status", "在线"),
            report_time=parsed.get("report_time"),
            raw_payload=json.dumps(parsed, ensure_ascii=False, default=str),
        )

        candidates = build_alarm_candidates_v2(
            db,
            device_type=device_type,
            device_no=parsed["device_no"],
            device_name=device_name,
            project_id=project_id,
            parsed=parsed,
            location=loc,
        )
        # 活跃违规集合：violation_key -> 仍打开告警的 id，用于自动结束已解除的告警
        current_violations: dict[str, int] = {}
        r = get_redis_client()
        for c in candidates:
            a = create_alarm(db, **c)
            if a is not None:
                created_alarms.append(a)
            # 仅对「告警开始」类(FENCE/DISTANCE)做生命周期配对；设备自报为离散事件
            if c.get("alarm_status") == ALARM_STATUS_START:
                vk = dedup_key(
                    c["alarm_type"],
                    c["device_no"],
                    c.get("fence_name"),
                    c["alarm_status"],
                    c.get("work_plan_id"),
                )
                if a is not None:
                    current_violations[vk] = a.id
                else:
                    # 去重命中：打开告警 id 记录在去重键中
                    mid = r.get(vk)
                    if mid:
                        try:
                            current_violations[vk] = int(mid)
                        except (TypeError, ValueError):
                            pass
        # 违规解除 → 自动结束上一轮仍打开的对应告警
        reconcile_active_alarms(db, parsed["device_no"], current_violations)

        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.exception("上行处理失败 device=%s/%s: %s", device_type, parsed.get("device_no"), exc)
        if own:
            db.rollback()
        raise
    finally:
        if own:
            db.close()

    # 推送（commit 后，跨线程安全）
    if loc is not None:
        channel = ws_channel_for_project(project_id)
        loc_msg = _location_to_ws(loc)
        bridge.emit(channel, loc_msg)
        bridge.emit("global", loc_msg)
        for a in created_alarms:
            msg = {"type": "alarm", "data": to_alarm_out(a)}
            bridge.emit(channel, msg)
            bridge.emit("global", msg)

    return {
        "device_no": parsed["device_no"],
        "device_type": device_type,
        "project_id": project_id,
        "alarms_created": len(created_alarms),
    }
