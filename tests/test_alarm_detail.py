"""告警详情端点测试（大屏·告警详情页 GET /v1/alarms/{alarm_id}）。

覆盖：
- 详情返回完整字段（含新增的 project_name / created_at）；
- 不存在的 id → 404；
- **路由遮蔽回归**：`/{alarm_id}` 是贪婪路径参数，必须注册在所有字面量子路径之后。
  本用例逐个请求 /config、/report、/period、/situation、/preventive-summary、
  /snapshot/preview、/daily，断言它们不会被 `/{alarm_id}` 吞掉（即不返回
  「路径参数解析失败」类响应）。若有人把详情端点上移，这些用例会立刻变红。
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.project import Project


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def project(db_session):
    p = Project(name="__t__alarm_detail_proj", dept_id=None, status="在建")
    db_session.add(p)
    db_session.flush()
    yield p
    db_session.execute(delete(Alarm).where(Alarm.project_id == p.id))
    db_session.execute(delete(Project).where(Project.id == p.id))
    db_session.commit()


@pytest.fixture
def alarm(db_session, project):
    a = Alarm(
        project_id=project.id,
        alarm_type="fence_intrusion",
        device_type="person",
        device_name="安全帽A",
        device_no="AD-DETAIL-001",
        alarm_info="人员（张三）进入围栏（1号围栏）触发告警",
        alarm_level="警告",
        alarm_status="告警开始",
        handle_status="待处理",
        fence_name="1号围栏",
        alarm_time=datetime.now(timezone.utc),
    )
    db_session.add(a)
    db_session.flush()
    db_session.commit()
    return a


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_get_alarm_detail_returns_full_fields(client, admin_token, alarm, project):
    """详情端点返回完整字段，含新增的 project_name / created_at。"""
    r = client.get(f"/api/v1/alarms/{alarm.id}", headers=_auth(admin_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    data = body["data"]
    assert data["id"] == alarm.id
    assert data["project_id"] == project.id
    # 新增字段：告警详情页顶部「项目名称」直接取用，避免前端二次请求项目接口
    assert data["project_name"] == project.name
    assert data["alarm_type"] == "fence_intrusion"
    assert data["fence_name"] == "1号围栏"
    assert data["alarm_info"] == "人员（张三）进入围栏（1号围栏）触发告警"
    assert data["handle_status"] == "待处理"
    assert data["alarm_time"]
    assert data["created_at"]
    assert isinstance(data["media_urls"], list)


def test_get_alarm_detail_not_found(client, admin_token):
    """不存在的告警 id → 404（HTTPException 走真实状态码）。"""
    r = client.get("/api/v1/alarms/99999999", headers=_auth(admin_token))
    assert r.status_code == 404, r.text


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/alarms/config",
        "/api/v1/alarms/situation",
        "/api/v1/alarms/preventive-summary",
        "/api/v1/alarms/report",
        "/api/v1/alarms/daily",
        "/api/v1/alarms/period",
        "/api/v1/alarms/snapshot/preview",
    ],
)
def test_literal_subpaths_not_shadowed_by_alarm_id(client, admin_token, path):
    """回归：字面量子路径不得被 `/{alarm_id}` 贪婪匹配吞掉。

    若详情端点被误移到这些端点之前，FastAPI 会尝试把 "config"/"report" 等
    解析为 int 型 alarm_id，产生 loc=['path','alarm_id'] 的校验错误。
    本项目 RequestValidationError 统一转成 HTTP 200 + body.code=422，
    因此只要断言「校验错误不来自 path.alarm_id」即可精确识别遮蔽，
    同时不误伤这些端点自身的必填 query 参数校验（如 /daily 需要 date）。
    """
    r = client.get(path, headers=_auth(admin_token))
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"
    body = r.json()
    if body.get("code") == 0:
        return  # 正常返回，未被遮蔽
    details = body.get("data") or []
    if isinstance(details, list):
        for item in details:
            loc = item.get("loc") if isinstance(item, dict) else None
            assert loc != ["path", "alarm_id"], f"{path} 被 /{{alarm_id}} 遮蔽：{body}"
    # 其余（如缺必填 query）属端点自身校验，与路由遮蔽无关，放行


def test_alarm_id_route_registered_last(client):
    """结构性断言：OpenAPI 中 `/{alarm_id}` 的注册顺序晚于所有字面量子路径。

    直接从 app.openapi() 取路径顺序（api_router.routes 遍历不到 path），
    比逐个请求更稳，可拦截未来新增字面量端点时误插到详情端点之后的情况。
    """
    from app.main import app

    paths = list(app.openapi()["paths"].keys())
    prefix = "/api/v1/alarms"
    detail_path = f"{prefix}/{{alarm_id}}"
    assert detail_path in paths, f"详情端点未注册：{[p for p in paths if prefix in p]}"
    detail_idx = paths.index(detail_path)
    literals = [
        p
        for p in paths
        if p.startswith(prefix + "/") and "{" not in p.replace(prefix, "", 1) and p != detail_path
    ]
    late = [p for p in literals if paths.index(p) > detail_idx]
    assert not late, f"以下字面量端点注册在 /{{alarm_id}} 之后，会被遮蔽：{late}"
