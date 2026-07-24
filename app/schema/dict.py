"""数据字典 Schema：字典类型与字典项的创建/更新/输出/分页。

字典为全局配置（不绑定项目/部门），时间字段统一以「北京时间墙钟」字符串对外。
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.core.clock import LOCAL_TZ


class DictItemBase(BaseModel):
    label: str = Field(..., description="显示名称")
    value: str = Field(..., description="存储值")
    sort: int = Field(0, description="排序(升序)")
    enabled: bool = True
    remark: str | None = None
    ext: str | None = Field(None, description="扩展字段(颜色/图标等)")


class DictItemCreate(DictItemBase):
    pass


class DictItemUpdate(BaseModel):
    label: str | None = None
    value: str | None = None
    sort: int | None = None
    enabled: bool | None = None
    remark: str | None = None
    ext: str | None = None


class DictItemOut(DictItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type_code: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class DictTypeCreate(BaseModel):
    code: str = Field(..., description="类型编码(唯一)")
    name: str = Field(..., description="类型名称")
    description: str | None = None
    items: list[DictItemCreate] = Field(default_factory=list, description="初始字典项")


class DictTypeUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class DictTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    system: bool = False
    items: list[DictItemOut] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_serializer("created_at", "updated_at")
    def _serialize_dt(self, v: datetime | None) -> str | None:
        if v is None:
            return None
        return v.astimezone(LOCAL_TZ).replace(tzinfo=None).isoformat()


class DictTypePage(BaseModel):
    total: int
    items: list[DictTypeOut]
    page: int = 1
    size: int = 20
