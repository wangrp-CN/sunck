"""地图资源库服务层：CRUD 与名称去重、软删。

- 地图资源为全局配置，不施加部门数据隔离；按 map:* 权限管控。
- 端点统一提交（service 不 commit）。
"""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import BusinessError
from app.model.map_asset import MapAsset


def list_assets(
    db: Session,
    keyword: str | None = None,
    asset_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[MapAsset]]:
    """分页列出地图资源（按 id 倒序）；支持名称/备注/维护人模糊与类型过滤。"""
    stmt = select(MapAsset).where(MapAsset.is_deleted.is_(False))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                MapAsset.name.ilike(like),
                MapAsset.remark.ilike(like),
                MapAsset.operator.ilike(like),
            )
        )
    if asset_type:
        stmt = stmt.where(MapAsset.type == asset_type)
    stmt = stmt.order_by(MapAsset.id.desc())
    rows = list(db.scalars(stmt).all())
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def get_asset(db: Session, asset_id: int) -> MapAsset | None:
    return db.scalar(
        select(MapAsset).where(MapAsset.id == asset_id, MapAsset.is_deleted.is_(False))
    )


def create_asset(db: Session, data: dict) -> MapAsset:
    """创建地图资源；名称去重（软删范围内唯一）。"""
    name = (data.get("name") or "").strip()
    if not name:
        raise BusinessError("资源名称不能为空", code=400)
    if db.scalar(select(MapAsset).where(MapAsset.name == name, MapAsset.is_deleted.is_(False))):
        raise BusinessError(f"地图资源名称已存在：{name}", code=400)
    asset = MapAsset(**data)
    db.add(asset)
    db.flush()
    db.refresh(asset)
    return asset


def update_asset(db: Session, asset_id: int, data: dict) -> MapAsset:
    """更新地图资源；名称变更时校验去重。"""
    asset = get_asset(db, asset_id)
    if asset is None:
        raise BusinessError("地图资源不存在", code=404)
    new_name = data.get("name")
    if new_name is not None and new_name != asset.name:
        dup = db.scalar(
            select(MapAsset).where(
                MapAsset.name == new_name,
                MapAsset.is_deleted.is_(False),
                MapAsset.id != asset_id,
            )
        )
        if dup:
            raise BusinessError(f"地图资源名称已存在：{new_name}", code=400)
    for k, v in data.items():
        setattr(asset, k, v)
    db.flush()
    db.refresh(asset)
    return asset


def delete_asset(db: Session, asset_id: int) -> None:
    """软删地图资源。"""
    asset = get_asset(db, asset_id)
    if asset is None:
        raise BusinessError("地图资源不存在", code=404)
    asset.is_deleted = True
    db.flush()
