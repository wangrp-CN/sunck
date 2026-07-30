"""处置预案初始播种：为 6 类告警提供默认处置预案（知识库）。

幂等：按 name 存在性跳过，可重复执行。
mock 数据：工程初期无真实预案库时，先用结构化示例模板占位，后续由业务维护。
运行方式见 scripts/seed_playbooks.py。
"""

import json

from sqlalchemy import select

from app.core.constants import (
    ALARM_TYPE_ANOMALY,
    ALARM_TYPE_DEVICE,
    ALARM_TYPE_DISTANCE,
    ALARM_TYPE_FENCE,
    ALARM_TYPE_FORECAST,
    ALARM_TYPE_TRAIN,
)
from app.core.database import SessionLocal
from app.model.playbook import Playbook

# 默认预案模板（mock）：覆盖 6 类告警的通用处置要点与步骤。
_SEED_PLAYBOOKS: list[dict] = [
    {
        "name": "电子围栏侵入处置预案",
        "alarm_type": ALARM_TYPE_FENCE,
        "alarm_level": None,
        "summary": "现场核实入侵目标，判别误报/真实侵入并处置。",
        "steps": [
            "1. 调阅现场视频/定位，确认侵入目标（人/机械/车辆）与位置；",
            "2. 通过广播/对讲立即提醒现场作业人员注意安全；",
            "3. 若为误报（如飞鸟、巡检人员），在系统中标注并关闭；",
            "4. 若真实侵入，通知现场负责人前往驱离并上报，必要时暂停作业；",
            "5. 处置完成后填写处置说明并归档。",
        ],
        "trigger_condition": "电子围栏越界触发 fence_intrusion 告警。",
        "references": [
            {"title": "铁路线路安全保护区管理办法", "url": "https://example.com/kb/fence-reg"},
        ],
        "tags": "围栏,侵入,现场核实",
        "owner_role": "现场安全员",
        "est_minutes": 15,
    },
    {
        "name": "人机间距过近处置预案",
        "alarm_type": ALARM_TYPE_DISTANCE,
        "alarm_level": None,
        "summary": "立即警示机械与人员保持安全距离，复核作业边界。",
        "steps": [
            "1. 查看定位与间距数值，确认机械/人员身份；",
            "2. 触发机械紧急减速/停机指令并语音警示人员撤离；",
            "3. 复核作业计划边界，确认是否越界施工；",
            "4. 间距恢复正常后恢复作业，记录原因；",
            "5. 频繁触发需复核机械定位精度与作业方案。",
        ],
        "trigger_condition": "大机与人员间距低于安全距离阈值。",
        "references": [
            {
                "title": "大型机械邻近营业线施工安全细则",
                "url": "https://example.com/kb/machine-safety",
            },
        ],
        "tags": "间距,大机,安全",
        "owner_role": "机械指挥员",
        "est_minutes": 10,
    },
    {
        "name": "设备自报告警处置预案",
        "alarm_type": ALARM_TYPE_DEVICE,
        "alarm_level": None,
        "summary": "判定设备故障/离线，派单运维并跟踪恢复。",
        "steps": [
            "1. 查看设备状态与上报内容，区分故障/离线/低电量；",
            "2. 低电量：提醒充电并改用备用设备；",
            "3. 离线/故障：派单运维现场排查，必要时切换冗余设备；",
            "4. 影响关键监测的，临时人工巡检兜底；",
            "5. 恢复后验证数据正常并关闭告警。",
        ],
        "trigger_condition": "设备心跳丢失或自检异常上报。",
        "references": [
            {"title": "监测设备运维手册", "url": "https://example.com/kb/device-ops"},
        ],
        "tags": "设备,运维,故障",
        "owner_role": "运维工程师",
        "est_minutes": 30,
    },
    {
        "name": "列车接近预警处置预案",
        "alarm_type": ALARM_TYPE_TRAIN,
        "alarm_level": None,
        "summary": "确保人员机械撤离至安全区域，列车通过后再复工。",
        "steps": [
            "1. 确认列车接近方向与预计通过时间；",
            "2. 立即广播撤离，机械停机、人员撤至安全线以外；",
            "3. 封锁侵入线路的作业面，禁止抢越；",
            "4. 列车通过后确认现场安全再恢复作业；",
            "5. 记录接近事件与处置过程。",
        ],
        "trigger_condition": "列车接近预警设备检测到列车驶近。",
        "references": [
            {"title": "营业线施工列车防护办法", "url": "https://example.com/kb/train-protection"},
        ],
        "tags": "列车,撤离,防护",
        "owner_role": "现场防护员",
        "est_minutes": 10,
    },
    {
        "name": "趋势异常处置预案",
        "alarm_type": ALARM_TYPE_ANOMALY,
        "alarm_level": None,
        "summary": "复核异常序列来源，判断隐患并提前干预。",
        "steps": [
            "1. 调出异常序列曲线与基线，定位突变/漂移区间；",
            "2. 排查采集设备与外部环境（天气/施工）干扰；",
            "3. 结合现场视频/巡检确认是否存在真实隐患；",
            "4. 疑似隐患转「隐患治理」流程并指派处理人；",
            "5. 持续观察趋势，未消除前提高监测频次。",
        ],
        "trigger_condition": "四类监测序列统计基线法检出异常。",
        "references": [
            {"title": "智能监测异常研判指引", "url": "https://example.com/kb/anomaly-guide"},
        ],
        "tags": "趋势,异常,研判",
        "owner_role": "监测分析师",
        "est_minutes": 20,
    },
    {
        "name": "预测性预警处置预案",
        "alarm_type": ALARM_TYPE_FORECAST,
        "alarm_level": None,
        "summary": "基于预测窗口前置布防，降低越阈风险。",
        "steps": [
            "1. 查看预测曲线、越阈时刻与置信区间；",
            "2. 在预测窗口前完成现场布防与资源调配；",
            "3. 对高风险点位预置管控措施（限流/加固/值守）；",
            "4. 窗口期内加密监测，越阈即转为实时告警处置；",
            "5. 事后回溯预测准确率，优化模型参数。",
        ],
        "trigger_condition": "风险预测序列越过阈值（predictive_alert）。",
        "references": [
            {"title": "风险预测模型应用说明", "url": "https://example.com/kb/forecast-doc"},
        ],
        "tags": "预测,预警,布防",
        "owner_role": "风险管控岗",
        "est_minutes": 25,
    },
]


def seed_playbooks(db=None) -> dict:
    """初始化默认处置预案（mock）。返回 {created, skipped}。"""
    own_session = db is None
    if own_session:
        db = SessionLocal()
    try:
        created = 0
        skipped = 0
        for spec in _SEED_PLAYBOOKS:
            exists = db.scalar(
                select(Playbook.id).where(
                    Playbook.name == spec["name"], Playbook.is_deleted.is_(False)
                )
            )
            if exists:
                skipped += 1
                continue
            obj = Playbook(
                name=spec["name"],
                project_id=None,  # 全局通用预案
                alarm_type=spec["alarm_type"],
                alarm_level=spec["alarm_level"],
                enabled=True,
                summary=spec["summary"],
                steps=json.dumps(spec["steps"], ensure_ascii=False),
                trigger_condition=spec["trigger_condition"],
                references=json.dumps(spec["references"], ensure_ascii=False),
                tags=spec["tags"],
                owner_role=spec["owner_role"],
                est_minutes=spec["est_minutes"],
                note="系统初始 mock 预案，可按项目细化覆盖。",
                created_by=None,
            )
            db.add(obj)
            created += 1
        if own_session:
            db.commit()
        return {"created": created, "skipped": skipped}
    finally:
        if own_session:
            db.close()
