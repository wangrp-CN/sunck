"""地图手动绘制服务层：几何校验/度量计算 + CRUD + 名称去重 + 软删。

- 与地图资源库一致：全局配置，不施加部门数据隔离；按 map:* 权限管控。
- 端点统一提交（service 不 commit）。
- 几何统一以 `points: [[lng, lat], ...]`（GCJ-02）进出，落库序列化为 geometry JSON 文本。
"""

import json
import math

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.constants import (
    MAP_DRAWING_KIND_LINE,
    MAP_DRAWING_KIND_MODES,
    MAP_DRAWING_KIND_POINT,
    MAP_DRAWING_KINDS,
    MAP_DRAWING_MODES,
)
from app.core.exceptions import BusinessError
from app.model.map_drawing import MapDrawing

_EARTH_R = 6371008.8  # 平均地球半径(米)


def haversine_m(lng1: float, lat1: float, lng2: float, lat2: float) -> float:
    """两点间大圆距离（米）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def polyline_length_m(points: list[list[float]]) -> float:
    """折线总长度（米）。"""
    total = 0.0
    for i in range(1, len(points)):
        total += haversine_m(points[i - 1][0], points[i - 1][1], points[i][0], points[i][1])
    return round(total, 2)


def normalize_points(kind: str, points: list[list[float]] | None) -> list[list[float]]:
    """校验并规范化坐标串：经度 [-180,180]、纬度 [-90,90]；点=1 个、线>=2 个。"""
    raw = points or []
    cleaned: list[list[float]] = []
    for p in raw:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise BusinessError("坐标格式非法，应为 [经度, 纬度]", code=400)
        try:
            lng, lat = float(p[0]), float(p[1])
        except (TypeError, ValueError) as exc:  # pragma: no cover - 防御
            raise BusinessError("坐标必须为数字", code=400) from exc
        if not (-180.0 <= lng <= 180.0):
            raise BusinessError(f"经度超出范围：{lng}", code=400)
        if not (-90.0 <= lat <= 90.0):
            raise BusinessError(f"纬度超出范围：{lat}", code=400)
        cleaned.append([round(lng, 8), round(lat, 8)])

    if kind == MAP_DRAWING_KIND_POINT:
        if len(cleaned) != 1:
            raise BusinessError("画点需且仅需 1 个坐标", code=400)
    elif kind == MAP_DRAWING_KIND_LINE:
        if len(cleaned) < 2:
            raise BusinessError("画线至少需要 2 个坐标", code=400)
    return cleaned


def validate_kind_mode(kind: str, mode: str) -> None:
    if kind not in MAP_DRAWING_KINDS:
        raise BusinessError(f"标注类型非法：{kind}", code=400)
    if mode not in MAP_DRAWING_MODES:
        raise BusinessError(f"绘制模式非法：{mode}", code=400)
    allowed = MAP_DRAWING_KIND_MODES.get(kind, ())
    if mode not in allowed:
        raise BusinessError(f"{kind} 不支持绘制模式：{mode}", code=400)


def _apply_geometry(target: MapDrawing, kind: str, points: list[list[float]]) -> None:
    target.geometry = json.dumps(points, ensure_ascii=False)
    target.center_lng = points[0][0]
    target.center_lat = points[0][1]
    target.length_m = polyline_length_m(points) if kind == MAP_DRAWING_KIND_LINE else None


def list_drawings(
    db: Session,
    keyword: str | None = None,
    kind: str | None = None,
    mode: str | None = None,
    project_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[int, list[MapDrawing]]:
    """分页列出地图标注（按 id 倒序）；支持名称/备注/标注人模糊与类型、模式、项目过滤。"""
    stmt = select(MapDrawing).where(MapDrawing.is_deleted.is_(False))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                MapDrawing.name.ilike(like),
                MapDrawing.remark.ilike(like),
                MapDrawing.operator.ilike(like),
            )
        )
    if kind:
        stmt = stmt.where(MapDrawing.kind == kind)
    if mode:
        stmt = stmt.where(MapDrawing.mode == mode)
    if project_id is not None:
        stmt = stmt.where(MapDrawing.project_id == project_id)
    stmt = stmt.order_by(MapDrawing.id.desc())
    rows = list(db.scalars(stmt).all())
    total = len(rows)
    start = max(0, (page - 1) * size)
    return total, rows[start : start + size]


def get_drawing(db: Session, drawing_id: int) -> MapDrawing | None:
    return db.scalar(
        select(MapDrawing).where(MapDrawing.id == drawing_id, MapDrawing.is_deleted.is_(False))
    )


def create_drawing(db: Session, data: dict) -> MapDrawing:
    """创建地图标注；名称必填且去重（软删范围内唯一）。"""
    payload = dict(data)
    name = (payload.pop("name", None) or "").strip()
    if not name:
        raise BusinessError("标注名称不能为空", code=400)
    kind = payload.pop("kind", "")
    mode = payload.pop("mode", "")
    validate_kind_mode(kind, mode)
    points = normalize_points(kind, payload.pop("points", None))
    if db.scalar(
        select(MapDrawing).where(MapDrawing.name == name, MapDrawing.is_deleted.is_(False))
    ):
        raise BusinessError(f"标注名称已存在：{name}", code=400)

    row = MapDrawing(name=name, kind=kind, mode=mode, **payload)
    _apply_geometry(row, kind, points)
    db.add(row)
    db.flush()
    db.refresh(row)
    return row


def update_drawing(db: Session, drawing_id: int, data: dict) -> MapDrawing:
    """更新地图标注；名称变更时校验去重，几何变更时重算度量。"""
    row = get_drawing(db, drawing_id)
    if row is None:
        raise BusinessError("地图标注不存在", code=404)
    payload = dict(data)

    new_name = payload.pop("name", None)
    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            raise BusinessError("标注名称不能为空", code=400)
        if new_name != row.name:
            dup = db.scalar(
                select(MapDrawing).where(
                    MapDrawing.name == new_name,
                    MapDrawing.is_deleted.is_(False),
                    MapDrawing.id != drawing_id,
                )
            )
            if dup:
                raise BusinessError(f"标注名称已存在：{new_name}", code=400)
        row.name = new_name

    kind = payload.pop("kind", None) or row.kind
    mode = payload.pop("mode", None) or row.mode
    validate_kind_mode(kind, mode)
    row.kind, row.mode = kind, mode

    points = payload.pop("points", None)
    if points is not None:
        _apply_geometry(row, kind, normalize_points(kind, points))

    for k, v in payload.items():
        setattr(row, k, v)
    db.flush()
    db.refresh(row)
    return row


def delete_drawing(db: Session, drawing_id: int) -> None:
    """软删地图标注。"""
    row = get_drawing(db, drawing_id)
    if row is None:
        raise BusinessError("地图标注不存在", code=404)
    row.is_deleted = True
    db.flush()
