"""知识库服务（🅱 知识库自动检索关联链接）。

- CRUD：列表（按项目/来源/启用过滤）、详情、新增、编辑、逻辑删除；
- 检索 ``search_knowledge``：按标签重叠 + 中英文 token/bigram 相关性打分，
  确定性排序（分数降序，同分 id 降序），无需外部分词/向量依赖；
- 遵循 SOP：服务内不提交事务，由调用端点 / job 统一 commit。
"""

from __future__ import annotations

import logging
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.data_scope import DataScope, apply_data_scope
from app.model.knowledge import KnowledgeArticle
from app.model.project import Project
from app.schema.knowledge import KnowledgeCreate, KnowledgeUpdate

logger = logging.getLogger("rail_monitor.knowledge")

_CJK = re.compile(r"[一-鿿]+")
_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]")


def _norm(text: str | None) -> str:
    return (text or "").lower()


def _tokens(text: str | None) -> set[str]:
    return set(_TOKEN.findall(_norm(text)))


def _bigrams(text: str | None) -> set[str]:
    bg: set[str] = set()
    for run in _CJK.findall(_norm(text)):
        run = run.replace(" ", "")
        for i in range(len(run) - 1):
            bg.add(run[i : i + 2])
    return bg


def _split_tags(tags: str | None) -> set[str]:
    return {t.strip().lower() for t in (tags or "").split(",") if t.strip()}


def _score(query: str, query_tags: set[str], art) -> int:
    """相关性打分：标题命中权重最高，正文/标签次之。"""
    q_tokens = _tokens(query)
    q_bi = _bigrams(query)
    title_tokens = _tokens(art.title)
    title_bi = _bigrams(art.title)
    body = f"{art.summary} {art.content or ''}"
    body_tokens = _tokens(body)
    body_bi = _bigrams(body)
    a_tags = _split_tags(art.tags)

    score = 0
    score += 5 * len(q_tokens & title_tokens)
    score += 4 * len(q_bi & title_bi)
    score += 2 * len(q_tokens & body_tokens)
    score += 2 * len(q_bi & body_bi)
    score += 3 * len(query_tags & a_tags)
    # 整词子串命中（含 alarm_type 英文 key）
    for qt in q_tokens:
        if len(qt) >= 2 and qt in _norm(art.title):
            score += 2
    return score


def _base_stmt(scope: DataScope):
    stmt = select(KnowledgeArticle).where(
        KnowledgeArticle.is_deleted.is_(False), KnowledgeArticle.enabled.is_(True)
    )
    return apply_data_scope(stmt, KnowledgeArticle, scope)


def search_knowledge_scored(
    db: Session,
    scope: DataScope,
    query: str,
    *,
    limit: int = 10,
) -> list[tuple[KnowledgeArticle, int]]:
    """按查询语句检索知识库，返回 ``(条目, 相关性分数)`` 列表，按分数降序。"""
    rows = db.scalars(_base_stmt(scope)).all()
    q_tags = _split_tags(query)
    scored = [(r, _score(query, q_tags, r)) for r in rows]
    scored = [(r, s) for r, s in scored if s > 0]
    scored.sort(key=lambda x: (x[1], x[0].id), reverse=True)
    return scored[:limit]


def search_knowledge(
    db: Session,
    scope: DataScope,
    query: str,
    *,
    limit: int = 10,
) -> list[KnowledgeArticle]:
    """按查询语句检索知识库，返回按相关性降序排列的条目（不含打分，供关联链接使用）。"""
    return [r for r, _ in search_knowledge_scored(db, scope, query, limit=limit)]


def to_out(db: Session, obj: KnowledgeArticle) -> dict:
    out = obj.__dict__.copy()
    out.pop("_sa_instance_state", None)
    out["project_name"] = None
    if obj.project_id is not None:
        p = db.get(Project, obj.project_id)
        out["project_name"] = p.name if p else None
    return out


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def list_knowledge(
    db: Session,
    scope: DataScope,
    *,
    project_id: int | None = None,
    source: str | None = None,
    enabled: bool | None = None,
    page: int = 1,
    size: int = 20,
) -> dict:
    page = max(1, page)
    size = max(1, min(size, 200))
    stmt = select(KnowledgeArticle).where(KnowledgeArticle.is_deleted.is_(False))
    stmt = apply_data_scope(stmt, KnowledgeArticle, scope)
    if project_id is not None:
        stmt = stmt.where(KnowledgeArticle.project_id == project_id)
    if source is not None:
        stmt = stmt.where(KnowledgeArticle.source == source)
    if enabled is not None:
        stmt = stmt.where(KnowledgeArticle.enabled.is_(enabled))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(KnowledgeArticle.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return {"total": total, "items": rows, "page": page, "size": size}


def get_knowledge(db: Session, scope: DataScope, kid: int) -> KnowledgeArticle | None:
    return db.scalars(
        select(KnowledgeArticle).where(
            KnowledgeArticle.is_deleted.is_(False), KnowledgeArticle.id == kid
        )
    ).first()


def create_knowledge(
    db: Session, scope: DataScope, creator_id: int | None, data: KnowledgeCreate
) -> KnowledgeArticle:
    obj = KnowledgeArticle(
        title=data.title,
        url=data.url,
        summary=data.summary,
        source=data.source or "知识库",
        tags=data.tags,
        content=data.content,
        project_id=data.project_id,
        enabled=data.enabled,
        created_by=creator_id,
    )
    db.add(obj)
    db.flush()
    return obj


def update_knowledge(
    db: Session, scope: DataScope, kid: int, data: KnowledgeUpdate
) -> KnowledgeArticle | None:
    obj = get_knowledge(db, scope, kid)
    if obj is None:
        return None
    for f in ("title", "url", "summary", "source", "tags", "content"):
        v = getattr(data, f, None)
        if v is None:
            continue
        setattr(obj, f, v or None)
    if data.project_id is not None:
        obj.project_id = data.project_id or None
    if data.enabled is not None:
        obj.enabled = data.enabled
    db.flush()
    return obj


def delete_knowledge(db: Session, scope: DataScope, kid: int) -> bool:
    obj = get_knowledge(db, scope, kid)
    if obj is None:
        return False
    obj.is_deleted = True
    db.flush()
    return True
