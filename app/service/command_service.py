"""设备指令下发闭环服务。

把原本「发布即结束」的下发改造为可追踪的闭环：

- ``build_and_send``：建一条 ``DeviceCommand`` 记录（pending）→ 注入 ``cmd_id`` →
  发布到 ``device/{type}/{no}/down`` → 状态置 ``sent``（发布失败则 ``failed``）。
- ``ack_command``：设备经 ``device/{no}/ack`` 回执 ``cmd_id``，据之更新为 ``acked``/``failed``。
- ``retry_command``：手动重试（运维在指令记录页点「重试」）。
- ``retry_stale_commands``：周期任务，对超时未回执或失败的指令自动重试直至达到上限。

状态机：``pending → sent → acked / failed``。所有写操作均自行 ``commit``，
调用方无需再提交；发布异常被捕获并落到 ``last_error``，不影响业务主流程。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.core.clock import now_local
from app.core.constants import down_topic
from app.core.exceptions import BusinessError
from app.model.command import (
    COMMAND_STATUS_ACKED,
    COMMAND_STATUS_FAILED,
    COMMAND_STATUS_PENDING,
    COMMAND_STATUS_SENT,
    DeviceCommand,
)
from app.mqtt import protocol
from app.mqtt.client import publish

logger = logging.getLogger("rail_monitor.command")


def _serialize(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _publish_now(cmd: DeviceCommand) -> None:
    """用已落库指令的字段重新发布；成功置 sent，失败置 failed。

    仅更新状态相关字段，由调用方统一 commit。
    """
    try:
        payload = protocol.build_command(
            cmd.device_type, cmd.action, cmd.params_json, cmd_id=cmd.id
        )
        topic = down_topic(cmd.device_type, cmd.device_no)
        payload_str = _serialize(payload)
        publish(topic, payload_str, qos=1)
        cmd.payload = payload_str
        cmd.topic = topic
        cmd.status = COMMAND_STATUS_SENT
        cmd.sent_at = now_local()
        cmd.last_error = None
    except Exception as exc:  # noqa: BLE001
        cmd.status = COMMAND_STATUS_FAILED
        cmd.last_error = f"发布失败: {exc}"[:500]


def build_and_send(
    db: Session,
    *,
    device_no: str,
    device_type: str,
    action: str,
    params: dict | None = None,
    project_id: int | None = None,
    device_id: int | None = None,
    actor_id: int | None = None,
    alarm_id: int | None = None,
) -> DeviceCommand:
    """构建并下发一条设备指令，持久化全生命周期记录。

    返回已落库的 ``DeviceCommand``（``status`` 为 ``sent`` 或 ``failed``）。
    """
    cmd = DeviceCommand(
        device_no=device_no,
        device_type=device_type,
        project_id=project_id,
        device_id=device_id,
        action=action,
        params_json=params,
        status=COMMAND_STATUS_PENDING,
        created_by=actor_id,
        alarm_id=alarm_id,
    )
    # 先校验动作/参数合法性（非法直接抛 BusinessError，不落库残留记录）。
    try:
        protocol.build_command(device_type, action, params)
    except protocol.ProtocolError as exc:
        raise BusinessError(str(exc), code=400)
    db.add(cmd)
    db.flush()  # 取 cmd.id 作为 cmd_id 注入报文
    _publish_now(cmd)
    db.commit()
    db.refresh(cmd)
    return cmd


def ack_command(
    db: Session, cmd_id: int, ok: bool, detail: str | None = None
) -> DeviceCommand | None:
    """处理设备回执，更新指令状态。幂等（已回执的重复回执直接忽略）。"""
    cmd = db.scalar(select(DeviceCommand).where(DeviceCommand.id == cmd_id))
    if cmd is None:
        logger.warning("收到未知指令回执 cmd_id=%s", cmd_id)
        return None
    if cmd.status == COMMAND_STATUS_ACKED:
        return cmd
    cmd.status = COMMAND_STATUS_ACKED if ok else COMMAND_STATUS_FAILED
    cmd.acked_at = now_local()
    if detail:
        cmd.last_error = f"回执: {detail}"[:500]
    db.commit()
    db.refresh(cmd)
    return cmd


def retry_command(db: Session, cmd_id: int) -> DeviceCommand:
    """手动重试一条指令（运维在指令记录页触发）。"""
    cmd = db.scalar(select(DeviceCommand).where(DeviceCommand.id == cmd_id))
    if cmd is None:
        raise BusinessError("指令记录不存在", code=404)
    if cmd.status == COMMAND_STATUS_ACKED:
        raise BusinessError("指令已回执，无需重试", code=400)
    cmd.retry_count += 1
    _publish_now(cmd)
    db.commit()
    db.refresh(cmd)
    return cmd


def retry_stale_commands(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """周期重试：对超时未回执（sent 且超过 ack 超时）或失败且未达上限的指令重新发布。

    达到 ``command_max_retries`` 仍失败的置为 ``failed``（不再自动重试）。
    返回统计：``{retried, exhausted, total}``。
    """
    now = now or now_local()
    timeout = timedelta(seconds=settings.command_ack_timeout_seconds)
    max_r = settings.command_max_retries

    stale = db.scalars(
        select(DeviceCommand).where(
            DeviceCommand.status == COMMAND_STATUS_SENT,
            DeviceCommand.sent_at < now - timeout,
        )
    ).all()

    retried = 0
    exhausted = 0
    for cmd in stale:
        if cmd.retry_count < max_r:
            cmd.retry_count += 1
            _publish_now(cmd)
            retried += 1
        else:
            cmd.status = COMMAND_STATUS_FAILED
            cmd.last_error = f"重试 {cmd.retry_count} 次仍未回执，已停止自动重试"[:500]
            exhausted += 1
    if stale:
        db.commit()
    return {"retried": retried, "exhausted": exhausted, "total": len(stale)}
