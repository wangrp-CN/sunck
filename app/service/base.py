"""通用 CRUD 服务基类。

约定：业务服务继承此类，注入 Session，提供基础的增删改查与分页能力。
数据隔离过滤等由各域服务在传入 stmt 时自行处理（见 app.core.data_scope）。
"""

from typing import Generic, Sequence, TypeVar

from sqlalchemy import Select, func, select
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

    def update(self, obj_id: int, **fields) -> ModelType | None:
        """按主键更新指定字段；对象不存在返回 None。"""
        obj = self.get(obj_id)
        if obj is None:
            return None
        for key, value in fields.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        self.db.commit()
        self.db.refresh(obj)
        return obj

    def delete(self, obj: ModelType) -> None:
        self.db.delete(obj)
        self.db.commit()

    def paginate(
        self, stmt: Select | None = None, page: int = 1, page_size: int = 20
    ) -> tuple[Sequence[ModelType], int]:
        """通用分页：返回 (当前页对象列表, 总记录数)。page 从 1 开始。"""
        stmt = stmt or select(self.model)
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self.db.scalar(count_stmt) or 0
        offset = (max(page, 1) - 1) * page_size
        rows = self.db.scalars(stmt.offset(offset).limit(page_size)).all()
        return rows, total
