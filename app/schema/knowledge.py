"""知识库条目 schema（🅱 知识库自动检索关联链接）。

- 时间统一序列化为北京时间（本地 naive ISO），与项目既有 schema 约定一致；
- 编辑语义（``KnowledgeUpdate``）：空串 ``""`` 表示「清除该字段」，``None`` 表示「不修改」。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_serializer, field_validator

from app.core.clock import LOCAL_TZ


def _ser_dt(v: datetime | None) -> str | None:
    if v is None:
        return None
    return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class KnowledgeBase(BaseModel):
    title: str
    url: str
    summary: str
    source: str = "知识库"
    tags: str | None = None
    content: str | None = None
    project_id: int | None = None
    enabled: bool = True

    @field_validator("title", "url", "summary")
    @classmethod
    def _v_required(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("标题/链接/摘要不可为空")
        return v

    @field_validator("tags")
    @classmethod
    def _v_tags(cls, v: str | None) -> str | None:
        return v.strip() if v else None


class KnowledgeCreate(KnowledgeBase):
    pass


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    url: str | None = None
    summary: str | None = None
    source: str | None = None
    tags: str | None = None
    content: str | None = None
    project_id: int | None = None
    enabled: bool | None = None

    # 编辑语义：空串 "" 表示「清除该字段」，None 表示「不修改」


class KnowledgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    url: str
    summary: str
    source: str = "知识库"
    tags: str | None = None
    content: str | None = None
    project_id: int | None = None
    project_name: str | None = None
    enabled: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        return _ser_dt(v)


class KnowledgeSearchItem(BaseModel):
    """检索命中的知识条目（含相关性评分）。"""

    id: int
    title: str
    url: str
    summary: str
    source: str
    tags: str | None = None
    score: int = 0
