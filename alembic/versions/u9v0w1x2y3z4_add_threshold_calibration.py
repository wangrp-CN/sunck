"""阈值自学习标定：risk_alert_threshold_calibration + risk_alert_threshold_override（#④-1）

- risk_alert_threshold_calibration：标定日志（追加式，审计阈值演进）。
- risk_alert_threshold_override：生效阈值单行覆盖（实现自学习→一键应用闭环）。

Revision Id: u9v0w1x2y3z4
Revises: t4u5v6w7x8y9
Create Date: 2026-07-27 16:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "u9v0w1x2y3z4"
down_revision: Union[str, Sequence[str], None] = "t4u5v6w7x8y9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risk_alert_threshold_calibration",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("target_breach_rate", sa.Float(), nullable=False),
        sa.Column("current_threshold", sa.Integer(), nullable=False),
        sa.Column("recommended_threshold", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False, server_default="quantile"),
        sa.Column("min_threshold", sa.Integer(), nullable=True),
        sa.Column("max_threshold", sa.Integer(), nullable=True),
        sa.Column("actual_breach_rate", sa.Float(), nullable=True),
        sa.Column("sweep_json", sa.Text(), nullable=True),
        sa.Column("stats_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ratc_created_at",
        "risk_alert_threshold_calibration",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "risk_alert_threshold_override",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("calibration_id", sa.Integer(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("risk_alert_threshold_override")
    op.drop_index("ix_ratc_created_at", table_name="risk_alert_threshold_calibration")
    op.drop_table("risk_alert_threshold_calibration")
