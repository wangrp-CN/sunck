"""规则引擎 v2 上行热路径回归测试。

重点守护 #4 修复：同一上行内若含多个「间距」触发的激活计划，
``latest_locations``（大机最新位置查询）应只调用 1 次（N→1），而非每计划各查 1 次。
"""

from unittest.mock import MagicMock, patch

from app.core import rule_engine_v2 as re2
from app.core.constants import ALARM_TYPE_DISTANCE, DEVICE_TYPE_LOCATE


def _fake_machine(device_no, lng=120.0, lat=30.0):
    m = MagicMock()
    m.device_no = device_no
    m.device_name = f"大机-{device_no}"
    m.longitude = lng
    m.latitude = lat
    m.status = "在线"
    return m


def _fake_plan(pid, triggers, dwell=0):
    p = MagicMock()
    p.id = pid
    p.rule_json = {"trigger_conditions": triggers, "dwell_time": dwell}
    return p


def test_build_candidates_hoists_latest_locations_once():
    """多个含「间距」触发的激活计划：latest_locations 仅查 1 次，且每个计划都产出候选。"""
    machines = [_fake_machine("M-1"), _fake_machine("M-2")]
    plans = [
        _fake_plan(1, [ALARM_TYPE_DISTANCE], dwell=0),
        _fake_plan(2, [ALARM_TYPE_DISTANCE], dwell=0),
        _fake_plan(3, ["fence_intrusion", ALARM_TYPE_DISTANCE], dwell=0),
    ]
    with (
        patch.object(re2, "load_active_plans", return_value=plans),
        patch.object(re2, "latest_locations", return_value=machines) as mock_ll,
        patch.object(re2, "_distance_threshold", return_value=50.0),
        patch.object(re2, "_plan_fences", return_value=[]),
        patch.object(re2, "_plan_reference_machines", side_effect=lambda db, plan, all_m: all_m),
        patch.object(re2, "_dwell_ok", return_value=True),
    ):
        db = MagicMock()
        cands = re2.build_alarm_candidates_v2(
            db,
            device_type=DEVICE_TYPE_LOCATE,
            device_no="LOC-1",
            device_name="loc",
            project_id=1,
            parsed={"device_no": "LOC-1", "longitude": 120.0, "latitude": 30.0},
            location=None,
        )

    # 关键断言：N 个含间距触发的计划，latest_locations 仅被调用 1 次（N→1 提循环外）
    assert mock_ll.call_count == 1, mock_ll.call_args_list
    # 未因 hoist 而漏判：2 台大机均落入阈值，3 个计划各产出 2 条间距候选
    dist = [c for c in cands if c["alarm_type"] == ALARM_TYPE_DISTANCE]
    assert len(dist) == 6, cands
    assert {c["work_plan_id"] for c in dist} == {1, 2, 3}


def test_build_candidates_no_latest_locations_when_no_distance():
    """纯围栏/设备计划不含间距触发时，不应触发 latest_locations 查询。"""
    plans = [_fake_plan(1, ["fence_intrusion"], dwell=0)]
    with (
        patch.object(re2, "load_active_plans", return_value=plans),
        patch.object(re2, "latest_locations", return_value=[]) as mock_ll,
        patch.object(re2, "_distance_threshold", return_value=50.0),
        patch.object(re2, "_plan_fences", return_value=[]),
        patch.object(re2, "_dwell_ok", return_value=True),
    ):
        db = MagicMock()
        re2.build_alarm_candidates_v2(
            db,
            device_type=DEVICE_TYPE_LOCATE,
            device_no="LOC-1",
            device_name="loc",
            project_id=1,
            parsed={"device_no": "LOC-1", "longitude": 120.0, "latitude": 30.0},
            location=None,
        )
    assert mock_ll.call_count == 0, "无间距触发时不应查询大机最新位置"
