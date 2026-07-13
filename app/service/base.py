"""通用 CRUD 服务基类（骨架）。

约定：业务服务继承此类，注入 Session，提供基础的增删改查能力。
具体实现在后续阶段补充（含 RBAC 数据隔离、规则引擎等）。
"""

from typing import Generic, Sequence, TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.model.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class CRUDService(Generic[ModelType]):
    model: type[ModelType]

    def __init__(self, db: Session):
        self.db = db

    def get(self, obj_id: int) -> ModelType | None:
        return self.db.get(self.model, obj_id)

    def list(self, stmt: Select | None = None) -> Sequence[ModelType]:
        stmt = stmt or select(self.model)
        return self.db.scalars(stmt).all()

    def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.commit()

    # 更新/分页/数据隔离过滤器等在此扩展（TODO）
