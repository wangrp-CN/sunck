"""菜单管理 Schema：基于 Permission 模型的菜单树操作。

菜单类型枚举：
- 1=目录（sub-menu group）
- 2=菜单（menu item / 页面）
- 3=按钮/接口（权限码）
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ

# ── 创建 / 更新 ──────────────────────────────────────────────


class MenuCreate(BaseModel):
    """新建菜单（目录、菜单项或按钮）。"""

    name: str = Field(..., min_length=1, max_length=64, description="菜单名称")
    code: str = Field(..., min_length=1, max_length=100, description="权限标识")
    type: int = Field(2, ge=1, le=3, description="类型: 1=目录 2=菜单 3=按钮")
    parent_id: int | None = Field(None, description="上级菜单ID")
    path: str | None = Field(None, max_length=200, description="前端路由路径")
    component: str | None = Field(None, max_length=200, description="前端组件路径")
    icon: str | None = Field(None, max_length=64, description="图标名称")
    sort: int = Field(0, ge=0, description="排序号")
    status: bool = Field(True, description="是否启用")
    redirect: str | None = Field(None, max_length=200, description="默认跳转地址")
    is_hidden: bool = Field(False, description="是否隐藏路由")
    is_cache: bool = Field(False, description="是否缓存路由(KeepAlive)")
    is_affix: bool = Field(False, description="是否聚合路由")
    is_external: bool = Field(False, description="是否外链(外部打开)")
    remark: str | None = Field(None, max_length=255, description="备注")


class MenuUpdate(BaseModel):
    """更新菜单（字段均为可选，仅传需要修改的字段）。"""

    name: str | None = Field(None, min_length=1, max_length=64, description="菜单名称")
    code: str | None = Field(None, min_length=1, max_length=100, description="权限标识")
    type: int | None = Field(None, ge=1, le=3, description="类型")
    parent_id: int | None = Field(None, description="上级菜单ID")
    path: str | None = Field(None, max_length=200, description="前端路由路径")
    component: str | None = Field(None, max_length=200, description="前端组件路径")
    icon: str | None = Field(None, max_length=64, description="图标名称")
    sort: int | None = Field(None, ge=0, description="排序号")
    status: bool | None = Field(None, description="是否启用")
    redirect: str | None = Field(None, max_length=200, description="默认跳转地址")
    is_hidden: bool | None = Field(None, description="是否隐藏路由")
    is_cache: bool | None = Field(None, description="是否缓存路由(KeepAlive)")
    is_affix: bool | None = Field(None, description="是否聚合路由")
    is_external: bool | None = Field(None, description="是否外链(外部打开)")
    remark: str | None = Field(None, max_length=255, description="备注")


# ── 输出 ────────────────────────────────────────────────────


class MenuOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    type: int
    parent_id: int | None = None
    path: str | None = None
    component: str | None = None
    icon: str | None = None
    sort: int = 0
    status: bool = True
    redirect: str | None = None
    is_hidden: bool = False
    is_cache: bool = False
    is_affix: bool = False
    is_external: bool = False
    remark: str | None = None
    is_deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at")
    def _serialize_created(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()

    @field_serializer("updated_at")
    def _serialize_updated(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class MenuTreeOut(MenuOut):
    """树形菜单节点，携带下级 children。"""

    children: list["MenuTreeOut"] = []
