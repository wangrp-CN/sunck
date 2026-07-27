"""智能核心 v2：跨设备根因关联（#77）测试。

覆盖：
- ``compute_correlations``：同围栏 + 多设备 + 时间近邻 → 1 个跨设备事件组；
  时间窗间隔超阈值 → 切分为 2 个事件组；无围栏无定位 → 单机事件组；
- 接口：``GET /metrics/correlations`` 鉴权与跨设备返回、``GET /.../{id}/members`` 成员明细、
  ``POST /metrics/correlations/run`` 仅超管可触发。

测试前后清空 correlated_event_group，并清理本次创建的告警，保证隔离。
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.database import SessionLocal
from app.model.alarm import Alarm
from app.model.correlation import CorrelatedEventGroup
from app.model.project import Project


@pytest.fixture
def wipe():
    # 清理关联组 + 本测试遗留的告警（测试库持久化，避免跨用例污染）
    db = SessionLocal()
    try:
        db.execute(delete(CorrelatedEventGroup))
        db.execute(delete(Alarm).where(Alarm.fence_name.like("%C77%")))
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.execute(delete(CorrelatedEventGroup))
        db.execute(delete(Alarm).where(Alarm.fence_name.like("%C77%")))
        db.commit()
    finally:
        db.close()


def _add_alarm(db, project_id, device_no, fence_name, when, level="警告"):
    a = Alarm(
        project_id=project_id,
        device_no=device_no,
        device_name=f"设备{ddevice_no_tail(device_no)}",
        fence_name=fence_name,
        alarm_type="防侵限",
        alarm_level=level,
        alarm_status="告警开始",
        handle_status="待处理",
        alarm_time=when,
        alarm_info="测试告警",
    )
    db.add(a)
    return a


def ddevice_no_tail(no: str) -> str:
    return no[-4:] if len(no) > 4 else no


def test_correlation_clusters_cross_device(wipe):
    """同围栏 + 3 台不同设备 + 时间近邻 → 1 个跨设备事件组；间隔超 30min → 切分第 2 组。"""
    db = SessionLocal()
    created: list[Alarm] = []
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None, "需存在真实项目"
        now = datetime.now(timezone.utc)
        fence = "测试围栏C77"

        # 簇 1：3 台不同设备，时间近邻（<30min）
        for i, dev in enumerate(["DEV-A-0001", "DEV-B-0002", "DEV-C-0003"]):
            a = _add_alarm(
                db,
                pid,
                dev,
                fence,
                now - timedelta(minutes=5 * i),
                level="严重" if i == 0 else "警告",
            )
            created.append(a)
        # 簇 2：同围栏，但时间远（>30min），应拆分为独立事件组
        a2 = _add_alarm(db, pid, "DEV-D-0004", fence, now - timedelta(minutes=90), level="提示")
        created.append(a2)
        db.commit()

        from app.service import alarm_correlation as corr_svc

        res = corr_svc.compute_correlations(db, window_hours=24, cluster_gap_minutes=30)
        assert res["groups"] >= 2
        assert res["cross_device_groups"] >= 1

        # 找到该围栏的两个事件组
        groups = db.scalars(
            select(CorrelatedEventGroup).where(CorrelatedEventGroup.fence_name == fence)
        ).all()
        assert len(groups) == 2, f"同围栏应切分为 2 个事件组，实际 {len(groups)}"

        cross = [g for g in groups if g.is_cross_device]
        assert len(cross) == 1, "仅簇1（3设备）应为跨设备"
        assert cross[0].device_count == 3
        assert cross[0].max_level == "严重"
        assert cross[0].alarm_count == 3

        # 成员明细
        members = corr_svc.get_correlation_members(db, cross[0].id, _all_scope(db))
        assert members is not None
        assert len(members) == 3
        member_ids = {m["id"] for m in members}
        assert member_ids == set(cross[0].to_dict()["alarm_ids"])
    finally:
        # 清理本次创建的告警，避免污染
        for a in created:
            db.delete(a)
        db.commit()
        db.close()


def test_correlation_device_only(wipe):
    """无围栏名、且无设备定位 → 退化为单机事件组（非跨设备）。"""
    db = SessionLocal()
    created: list[Alarm] = []
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        assert pid is not None
        now = datetime.now(timezone.utc)
        # 同一台无定位设备，连续 2 条告警 → 单机簇
        for i in range(2):
            a = _add_alarm(db, pid, "DEV-NOLOC-9", None, now - timedelta(minutes=i), level="提示")
            created.append(a)
        db.commit()

        from app.service import alarm_correlation as corr_svc

        corr_svc.compute_correlations(db, window_hours=24, cluster_gap_minutes=30)
        # 该设备应形成一个 device 类型、非跨设备的事件组
        dev_groups = db.scalars(
            select(CorrelatedEventGroup).where(
                CorrelatedEventGroup.spatial_type == "device",
                CorrelatedEventGroup.device_count == 1,
            )
        ).all()
        assert any(g.alarm_count == 2 for g in dev_groups), "单机 2 告警应成 1 组"
    finally:
        for a in created:
            db.delete(a)
        db.commit()
        db.close()


def test_correlations_endpoint(client: TestClient, admin_token: str, wipe):
    """GET /metrics/correlations：返回事件组；POST /run 仅超管；members 返回成员。"""
    h = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    created: list[Alarm] = []
    try:
        pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
        now = datetime.now(timezone.utc)
        fence = "端点围栏C77"
        for i, dev in enumerate(["EP-A-1001", "EP-B-1002"]):
            a = _add_alarm(db, pid, dev, fence, now - timedelta(minutes=3 * i), level="警告")
            created.append(a)
        db.commit()
    finally:
        db.close()

    # 手动触发计算（超管）
    r = client.post("/api/v1/metrics/correlations/run", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["cross_device_groups"] >= 1

    # 列表
    r = client.get("/api/v1/metrics/correlations", headers=h)
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    grp = next((it for it in items if it["fence_name"] == fence), None)
    assert grp is not None, "应返回该围栏事件组"
    assert grp["is_cross_device"] is True
    assert grp["device_count"] == 2

    # 成员明细
    r = client.get(f"/api/v1/metrics/correlations/{grp['id']}/members", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["total"] == 2

    # 不存在的组 → 业务码 404（项目约定：BusinessError 返回 HTTP200 + body code）
    r = client.get("/api/v1/metrics/correlations/999999/members", headers=h)
    assert r.status_code == 200
    assert r.json()["code"] == 404

    # 清理
    db = SessionLocal()
    try:
        for a in created:
            db.delete(a)
        db.commit()
    finally:
        db.close()


def test_correlations_run_requires_admin(client: TestClient, wipe):
    """POST /metrics/correlations/run 未登录应被拒绝。"""
    r = client.post("/api/v1/metrics/correlations/run")
    assert r.status_code in (401, 403)


def test_correlation_summary_and_trend(client: TestClient, admin_token: str, wipe):
    """汇总（今日跨设备共因计数 / 累计 / 按级别）+ 趋势（按 started_at 日期分桶）。"""
    h = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    try:
        pid = db.scalar(select(Project.id).where(Project.is_deleted.is_(False)))
        now = datetime.now(timezone.utc)
        today_mid = now.replace(hour=0, minute=0, second=0, microsecond=0)
        rows = [
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="fence",
                scope_key="F1",
                fence_name="F1",
                started_at=now,
                alarm_count=3,
                device_count=2,
                is_cross_device=True,
                max_level="严重",
                computed_at=now,
            ),
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="fence",
                scope_key="F2",
                fence_name="F2",
                started_at=now,
                alarm_count=2,
                device_count=2,
                is_cross_device=True,
                max_level="警告",
                computed_at=now,
            ),
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="device",
                scope_key="D1",
                started_at=now,
                alarm_count=1,
                device_count=1,
                is_cross_device=False,
                max_level="提示",
                computed_at=now,
            ),
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="fence",
                scope_key="F3",
                fence_name="F3",
                started_at=today_mid - timedelta(days=1),
                alarm_count=2,
                device_count=2,
                is_cross_device=True,
                max_level="警告",
                computed_at=now,
            ),
        ]
        db.add_all(rows)
        db.commit()
    finally:
        db.close()

    # 汇总
    r = client.get("/api/v1/metrics/correlations/summary", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["today_cross_device"] == 2
    assert d["cross_device_total"] == 3
    assert d["total"] == 4
    assert d["today_projects"] == 1
    assert d["by_level"].get("严重") == 1
    assert d["by_level"].get("警告") == 2

    # 趋势：仅跨设备，近 30 天；今日 2、昨日 1、其余补 0
    tr = client.get("/api/v1/metrics/correlations/trend?days=30&only_cross_device=true", headers=h)
    assert tr.status_code == 200, tr.text
    s = tr.json()["data"]["series"]
    assert len(s) == 30
    today_key = now.date().isoformat()
    y_key = (today_mid - timedelta(days=1)).date().isoformat()
    assert next(p for p in s if p["date"] == today_key)["count"] == 2
    assert next(p for p in s if p["date"] == y_key)["count"] == 1
    assert all(p["count"] == 0 for p in s if p["date"] not in (today_key, y_key))


def _all_scope(db):
    """构造一个「全部数据」DataScope（超管视角），供成员查询。"""
    from app.core.data_scope import DataScope

    return DataScope(is_all=True)


def test_correlation_heatmap_endpoint(client: TestClient, admin_token: str, wipe):
    """热力图：geo 组由 grid_cell 反解坐标；fence 组由成员设备最新定位均值解析；
    每点带原始 WGS-84 与转换后 gcj02，weight=告警数；only_cross_device 生效。"""
    import json

    from app.model.realtime import DeviceLocation

    h = {"Authorization": f"Bearer {admin_token}"}
    db = SessionLocal()
    dev_nos = ["HM-A-7001", "HM-B-7002"]
    loc_rows: list[DeviceLocation] = []
    try:
        pid = db.scalar(select(Project.id).where(Project.is_deleted.is_(False)))
        assert pid is not None
        now = datetime.now(timezone.utc)

        # 成员设备定位（WGS-84）：均值应为 (116.31, 39.81)
        db.execute(delete(DeviceLocation).where(DeviceLocation.device_no.in_(dev_nos)))
        for dno, (lng, lat) in zip(dev_nos, [(116.30, 39.80), (116.32, 39.82)]):
            loc = DeviceLocation(
                device_no=dno,
                project_id=pid,
                longitude=lng,
                latitude=lat,
                report_time=now,
                status="在线",
            )
            db.add(loc)
            loc_rows.append(loc)

        # geo 组：lat=39.90, lng=116.40 → grid_cell = "3990,11640"（与 _scope_of 编码对称）
        geo_cell = f"{round(39.90 / 0.01):.0f},{round(116.40 / 0.01):.0f}"
        rows = [
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="geo",
                scope_key=geo_cell,
                grid_cell=geo_cell,
                started_at=now,
                alarm_count=5,
                device_count=3,
                is_cross_device=True,
                max_level="严重",
                computed_at=now,
            ),
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="fence",
                scope_key="围栏C77H",
                fence_name="围栏C77H",
                device_nos=json.dumps(dev_nos),
                started_at=now,
                alarm_count=3,
                device_count=2,
                is_cross_device=True,
                max_level="警告",
                computed_at=now,
            ),
            # 单机、非跨设备：only_cross_device=True 时不应出现
            CorrelatedEventGroup(
                project_id=pid,
                project_name="P",
                spatial_type="device",
                scope_key="单机C77H",
                device_nos=json.dumps(["HM-A-7001"]),
                started_at=now,
                alarm_count=1,
                device_count=1,
                is_cross_device=False,
                max_level="提示",
                computed_at=now,
            ),
        ]
        db.add_all(rows)
        db.commit()
    finally:
        db.close()

    # 默认 only_cross_device=True：应返回 geo + fence 两个跨设备点
    r = client.get("/api/v1/metrics/correlations/heatmap", headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["only_cross_device"] is True
    pts = d["points"]
    assert d["total"] == len(pts)

    geo_pt = next((p for p in pts if p["spatial_type"] == "geo"), None)
    assert geo_pt is not None, "geo 组应解析坐标"
    assert abs(geo_pt["lng"] - 116.40) < 1e-6
    assert abs(geo_pt["lat"] - 39.90) < 1e-6
    assert geo_pt["weight"] == 5
    assert geo_pt["gcj02"]["lng"] != geo_pt["lng"], "gcj02 应与 WGS-84 有偏移"

    fence_pt = next((p for p in pts if p["spatial_type"] == "fence"), None)
    assert fence_pt is not None, "fence 组应由设备定位均值解析"
    assert abs(fence_pt["lng"] - 116.31) < 1e-6
    assert abs(fence_pt["lat"] - 39.81) < 1e-6
    assert fence_pt["weight"] == 3

    # 非跨设备的单机组不应出现在默认结果中
    assert all(p["is_cross_device"] for p in pts)

    # only_cross_device=false：单机组坐标可解析（成员设备有定位）→ 出现
    r2 = client.get("/api/v1/metrics/correlations/heatmap?only_cross_device=false", headers=h)
    assert r2.status_code == 200, r2.text
    pts2 = r2.json()["data"]["points"]
    assert any(p["spatial_type"] == "device" for p in pts2)

    # 清理定位数据（wipe 只清关联组与告警）
    db = SessionLocal()
    try:
        db.execute(delete(DeviceLocation).where(DeviceLocation.device_no.in_(dev_nos)))
        db.commit()
    finally:
        db.close()
