"""处置预案 schema（🅱 M5 处置预案/知识库联动）。

- ``steps`` / ``references`` 在 DB 中以 JSON 文本存储，schema 层负责与列表互转；
- 时间统一序列化为北京时间（本地 naive ISO），与项目既有 schema 约定一致；
- 编辑语义（``PlaybookUpdate``）：空串 ``""`` 表示「清除该字段」，``None`` 表示「不修改」。
"""

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator, model_validator

from app.core.clock import LOCAL_TZ

_VALID_LEVELS = ("提示", "警告", "严重")

_LEVEL_RE = re.compile(r"^(提示|警告|严重)$")


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


def _decode_json(text: Any, default: Any) -> Any:
    """把 DB 的 JSON 文本列解码为列表；非字符串（已是列表）则原样返回。"""
    if isinstance(text, str):
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return default
    if text is None:
        return default
    return text


def encode_json(value: Any) -> str:
    """把列表/字典序列化为 JSON 文本，供写入 DB。"""
    return json.dumps(value or [], ensure_ascii=False)


class PlaybookBase(BaseModel):
    name: str
    project_id: int | None = None
    alarm_type: str | None = None
    alarm_level: str | None = None
    enabled: bool = True
    summary: str
    steps: list[str] = []
    trigger_condition: str | None = None
    references: list[dict] = []
    tags: str | None = None
    owner_role: str | None = None
    est_minutes: int | None = None
    note: str | None = None

    @field_validator("steps")
    @classmethod
    def _v_steps(cls, v: list[str]) -> list[str]:
        return [str(s).strip() for s in (v or []) if str(s).strip()]

    @field_validator("references")
    @classmethod
    def _v_refs(cls, v: list[dict]) -> list[dict]:
        out = []
        for r in v or []:
            if isinstance(r, dict) and (r.get("title") or r.get("url")):
                out.append({"title": str(r.get("title", "")), "url": str(r.get("url", ""))})
        return out


class PlaybookCreate(PlaybookBase):
    pass


class PlaybookUpdate(BaseModel):
    name: str | None = None
    project_id: int | None = None
    alarm_type: str | None = None
    alarm_level: str | None = None
    enabled: bool | None = None
    summary: str | None = None
    steps: list[str] | None = None
    trigger_condition: str | None = None
    references: list[dict] | None = None
    tags: str | None = None
    owner_role: str | None = None
    est_minutes: int | None = None
    note: str | None = None

    # 编辑语义：空串 "" 表示「清除该字段」，None 表示「不修改」
    @field_validator("steps", "references")
    @classmethod
    def _v_list(cls, v: Any) -> Any:
        # None 表示不修改；空列表 [] 表示清空
        return v


class PlaybookOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    project_id: int | None = None
    project_name: str | None = None
    alarm_type: str | None = None
    alarm_level: str | None = None
    enabled: bool = True
    summary: str
    steps: list[str] = []
    trigger_condition: str | None = None
    references: list[dict] = []
    tags: str | None = None
    owner_role: str | None = None
    est_minutes: int | None = None
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _decode(cls, data: Any) -> Any:
        # ORM 对象或字典：把 JSON 文本列解码为列表
        if isinstance(data, dict):
            if isinstance(data.get("steps"), str):
                data = {**data, "steps": _decode_json(data["steps"], [])}
            if isinstance(data.get("references"), str):
                data = {**data, "references": _decode_json(data["references"], [])}
        return data

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return _ser_dt(v)
