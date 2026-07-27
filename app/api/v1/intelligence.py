"""智能核心深化路由（#④）。

- ``GET  /intelligence/threshold-calibration``：查看当前生效阈值 + 最近一次标定结果。
- ``POST /intelligence/threshold-calibration/calibrate``：基于历史分布标定推荐阈值（超管）。
- ``POST /intelligence/threshold-calibration/apply``：一键应用（覆盖生效阈值，超管）。

阈值自学习闭环：calibrate 落日志 → apply 写入单行覆盖 → 预警服务经
``get_active_threshold`` 读取，自动生效。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_current_user, require_permissions
from app.core.exceptions import BusinessError
from app.core.responses import ApiResponse
from app.model.system import User
from app.service import threshold_calibration as tc

router = APIRouter(prefix="/v1/intelligence", tags=["智能核心"])


class CalibrateReq(BaseModel):
    window_days: int = Field(90, ge=7, le=365, description="标定回溯窗口（天）")
    target_breach_rate: float = Field(
        0.10, ge=0.01, le=0.5, description="目标越阈率（标定目标预算）"
    )
    min_threshold: int = Field(40, ge=0, le=100, description="推荐阈值下界")
    max_threshold: int = Field(90, ge=0, le=100, description="推荐阈值上界")


class ApplyReq(BaseModel):
    threshold: int = Field(..., ge=0, le=100, description="要应用的生效阈值")
    source: str = Field("manual", description="来源(auto/manual)")
    calibration_id: int | None = Field(None, description="来源标定记录 id（auto 时）")


def _require_superuser(current: User) -> None:
    if not current.is_superuser:
        raise BusinessError("仅超级管理员可管理智能核心阈值", code=403)


@router.get("/threshold-calibration")
def get_calibration(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("dashboard:view")),
):
    """查看当前生效阈值与最近一次标定结果。"""
    active = tc.get_active_threshold(db)
    latest = tc.get_latest_calibration(db)
    return ApiResponse.success(
        data={
            "active_threshold": active,
            "latest": latest.to_dict() if latest else None,
        }
    )


@router.post("/threshold-calibration/calibrate")
def calibrate(
    req: CalibrateReq,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """基于历史风险分布标定推荐阈值（超管）。落日志并返回扫描曲线。"""
    _require_superuser(current)
    result = tc.calibrate_threshold(
        db,
        req.window_days,
        req.target_breach_rate,
        req.min_threshold,
        req.max_threshold,
    )
    row = tc.persist_calibration(db, result)
    return ApiResponse.success(
        data={"calibration_id": row.id, **result},
        message="标定完成，可经 /apply 一键应用",
    )


@router.post("/threshold-calibration/apply")
def apply(
    req: ApplyReq,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """应用生效阈值覆盖（超管）。auto 来源可关联标定记录 id。"""
    _require_superuser(current)
    if req.source not in ("auto", "manual"):
        raise BusinessError("source 仅支持 auto / manual", code=400)
    ov = tc.apply_threshold(db, req.threshold, source=req.source, calibration_id=req.calibration_id)
    return ApiResponse.success(
        data={"active_threshold": ov.threshold, "source": ov.source},
        message=f"已应用阈值 {ov.threshold}（{ov.source}）",
    )
