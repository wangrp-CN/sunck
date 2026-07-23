"""操作审计域模型：记录关键写操作的「谁 / 何时 / 对哪个模块 / 做了什么 / 结果如何」。

- 由 `app.core.audit.AuditMiddleware` 对写请求（POST/PUT/PATCH/DELETE）自动落库；
- 落库时快照操作人的 `user_id` / `username` / `dept_id`，便于按部门数据范围检索
  （审计查阅受 `data_scope` 约束：仅可见本部门及下级的操作，与全站数据隔离一致）；
- `action` 由 HTTP 方法映射（create/update/delete），`module` 由路径前缀推导。
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"

    # 操作人快照（用户删除后仍能溯源；user_id 置空由 ON DELETE SET NULL 处理）
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="操作人ID(快照)",
    )
    username: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="操作人账号(快照)"
    )
    # 部门快照：用于审计列表按数据范围过滤（本部门及以下可见）
    dept_id: Mapped[int | None] = mapped_column(
        ForeignKey("department.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="操作人归属部门ID(快照)",
    )
    # 动作：create / update / delete / login 等（由 HTTP 方法映射，可扩展语义动作）
    action: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="操作动作")
    # 模块：由请求路径前缀推导，如 devices / hazards / alarms / realtime ...
    module: Mapped[str] = mapped_column(String(48), nullable=False, index=True, comment="业务模块")
    # 原始请求方法 / 路径 / 查询串（便于完整溯源）
    method: Mapped[str] = mapped_column(String(8), nullable=False, comment="HTTP方法")
    path: Mapped[str] = mapped_column(String(255), nullable=False, comment="请求路径")
    query: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="查询串")
    # 处理结果
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, comment="响应状态码")
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="客户端IP")
    # 备注（如失败原因、关键参数摘要）
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="操作详情")
