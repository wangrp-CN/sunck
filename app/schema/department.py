"""部门管理相关 Schema（请求/响应模型）。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DepartmentCreate(BaseModel):
    name: str = Field(..., max_length=64, description="部门名称")
    code: str = Field(
        ..., max_length=64, pattern=r"^[A-Za-z0-9_]+$", description="部门编码(字母数字下划线)"
    )
    parent_id: int | None = Field(None, description="上级部门ID(顶级为null)")
    leader: str | None = Field(None, max_length=64, description="负责人")
    phone: str | None = Field(None, max_length=32, description="联系电话")
    sort: int = Field(0, description="排序")
    status: bool = Field(True, description="是否启用")
    remark: str | None = Field(None, max_length=255, description="备注")


class DepartmentUpdate(BaseModel):
    name: str | None = Field(None, max_length=64, description="部门名称")
    parent_id: int | None = Field(None, description="上级部门ID")
    leader: str | None = Field(None, max_length=64, description="负责人")
    phone: str | None = Field(None, max_length=32, description="联系电话")
    sort: int | None = Field(None, description="排序")
    status: bool | None = Field(None, description="是否启用")
    remark: str | None = Field(None, max_length=255, description="备注")


class DepartmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    parent_id: int | None = None
    leader: str | None = None
    phone: str | None = None
    sort: int
    status: bool
    remark: str | None = None
    created_at: datetime | None = None


class DepartmentTree(DepartmentOut):
    children: list["DepartmentTree"] = Field(default_factory=list, description="下级部门")


DepartmentTree.model_rebuild()
