"""知识库路由（🅱 知识库自动检索关联链接）。

权限：
- knowledge:list   检索/列表/详情
- knowledge:manage 新增/编辑/删除

端点：
- GET    /search              相关性检索（knowledge:list）
- GET    /                    分页列表（knowledge:list）
- GET    /{kid}               详情（knowledge:list）
- POST   /                    新增（knowledge:manage）
- PUT    /{kid}               编辑（knowledge:manage）
- DELETE /{kid}               删除（knowledge:manage，逻辑删除）
"""

from fastapi import APIRouter, Depends, Query

from app.core.data_scope import DataScope
from app.core.database import get_db
from app.core.deps import get_current_user, get_data_scope, require_permissions
from app.core.responses import ApiResponse
from app.model.system import User
from app.schema.knowledge import (
    KnowledgeCreate,
    KnowledgeOut,
    KnowledgeSearchItem,
    KnowledgeUpdate,
)
from app.service import knowledge_service as svc

router = APIRouter(tags=["知识库"])

_SOURCES = ["规范库", "内训库", "案例库", "手册"]


def _out(db, obj) -> dict:
    return KnowledgeOut.model_validate(svc.to_out(db, obj)).model_dump()


@router.get(
    "/search",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:list"))],
)
def search(
    q: str = Query(..., min_length=1, description="检索语句"),
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    limit: int = Query(10, ge=1, le=30),
) -> ApiResponse:
    rows = svc.search_knowledge_scored(db, scope, q, limit=limit)
    data = [
        KnowledgeSearchItem(**svc.to_out(db, art), score=score).model_dump() for art, score in rows
    ]
    return ApiResponse.success(data=data)


@router.get(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:list"))],
)
def list_knowledge(
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    project_id: int | None = Query(None, description="按项目过滤"),
    source: str | None = Query(None, description="按来源过滤"),
    enabled: bool | None = Query(None, description="按启用状态过滤"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=200),
) -> ApiResponse:
    result = svc.list_knowledge(
        db, scope, project_id=project_id, source=source, enabled=enabled, page=page, size=size
    )
    return ApiResponse.success(
        data={
            "total": result["total"],
            "items": [_out(db, o) for o in result["items"]],
            "page": result["page"],
            "size": result["size"],
        }
    )


@router.get(
    "/{kid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:list"))],
)
def detail(kid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    obj = svc.get_knowledge(db, scope, kid)
    if obj is None:
        return ApiResponse.fail(code=404, message="知识条目不存在或无权访问")
    return ApiResponse.success(data=_out(db, obj))


@router.post(
    "/",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:manage"))],
)
def create(
    payload: KnowledgeCreate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
    user: User = Depends(get_current_user),
) -> ApiResponse:
    obj = svc.create_knowledge(db, scope, user.id, payload)
    db.commit()
    return ApiResponse.success(data=_out(db, obj))


@router.put(
    "/{kid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:manage"))],
)
def update(
    kid: int,
    payload: KnowledgeUpdate,
    db=Depends(get_db),
    scope: DataScope = Depends(get_data_scope),
) -> ApiResponse:
    obj = svc.update_knowledge(db, scope, kid, payload)
    if obj is None:
        return ApiResponse.fail(code=404, message="知识条目不存在或无权访问")
    db.commit()
    return ApiResponse.success(data=_out(db, obj))


@router.delete(
    "/{kid}",
    response_model=ApiResponse,
    dependencies=[Depends(require_permissions("knowledge:manage"))],
)
def delete(kid: int, db=Depends(get_db), scope: DataScope = Depends(get_data_scope)) -> ApiResponse:
    ok = svc.delete_knowledge(db, scope, kid)
    if not ok:
        return ApiResponse.fail(code=404, message="知识条目不存在或无权访问")
    db.commit()
    return ApiResponse.success(data={"deleted": True})
