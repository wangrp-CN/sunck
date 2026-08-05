"""系统日志域模型：记录应用运行时的异常、警告与关键事件。

与操作审计（AuditLog）的差异：
- AuditLog 记录「谁做了什么写操作」，由审计中间件自动落库；
- SystemLog 记录「系统发生了什么」，由应用内部各模块显式写入，
  聚焦异常堆栈、性能告警、连接中断等运维关注事件。

使用方式：通过 ``app.service.log_service.write_system_log()`` 在需要的地方写入。
"""

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.model.base import Base, TimestampMixin


class SystemLog(Base, TimestampMixin):
    __tablename__ = "system_log"

    # 日志级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
    level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="INFO", index=True, comment="日志级别"
    )
    # 业务模块标识，如 mqtt / db / redis / auth / forecast / websocket
    module: Mapped[str] = mapped_column(String(48), nullable=False, index=True, comment="来源模块")
    # 简短摘要
    message: Mapped[str] = mapped_column(String(512), nullable=False, comment="日志摘要")
    # 详细上下文（JSON 或自由文本），如堆栈、请求体、环境快照
    detail: Mapped[str | None] = mapped_column(Text, nullable=True, comment="详细上下文")
    # 异常全量堆栈（仅 ERROR/CRITICAL 级别写入，方便定位）
    traceback: Mapped[str | None] = mapped_column(Text, nullable=True, comment="异常堆栈")
    # 触发来源：可为空（如计划任务、健康检查）
    source: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="触发来源")
    # 关联操作人（若由用户操作间接触发，如上传文件失败）
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联用户ID",
    )
