"""知识库 mock 数据播种（🅱 知识库自动检索关联链接）。

幂等：按 title 去重，已存在则跳过。覆盖 6 类告警场景 + 通用处置条目，
标签同时含中文关键词与 alarm_type 英文 key，便于检索关联命中。

真实数据接入：替换本文件 _ARTICLES 后重跑 ``scripts/seed_rbac.py`` 即可。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.database import SessionLocal
from app.model.knowledge import KnowledgeArticle

_ARTICLES: list[dict] = [
    {
        "title": "《铁路线路防护栅栏管理办法》解读",
        "url": "https://kb.rail.local/standards/fence-mgmt",
        "summary": "防护栅栏侵入的处置原则、上报流程与现场隔离要求，明确限界与警戒设置。",
        "source": "规范库",
        "tags": "围栏,侵入,fence_intrusion,防护栅栏,限界,警戒",
        "content": "现场发现防护栅栏侵入应立即设置警戒线并上报工务段；大型机械侵入限界须立即叫停并组织下道避险。",
    },
    {
        "title": "铁路营业线施工安全管理办法（安全距离）",
        "url": "https://kb.rail.local/standards/work-distance",
        "summary": "设备、机械与铁路线路的安全距离规定，间距过近的预警与处置要求。",
        "source": "规范库",
        "tags": "间距,距离,distance,限界,施工安全,机械",
        "content": "施工机械与线路中心距离不足时应停止作业，设置防护员并通知列车调度员。",
    },
    {
        "title": "监测设备离线/故障排查 SOP",
        "url": "https://kb.rail.local/sop/device-trouble",
        "summary": "监测设备离线、数据中断的现场排查步骤与备件更换流程。",
        "source": "内训库",
        "tags": "设备,离线,故障,device,监测,排查",
        "content": "先确认供电与通信链路，重启网关；仍异常则更换备用机并登记设备编号。",
    },
    {
        "title": "列车接近预警现场避险规程",
        "url": "https://kb.rail.local/sop/train-approach",
        "summary": "列车接近预警触发后，现场人员下道、撤离与防护员联控要求。",
        "source": "内训库",
        "tags": "列车,接近,train,避险,下道,防护员",
        "content": "接到列车接近预警，所有人员立即下道至安全限界外，防护员持红牌迎车。",
    },
    {
        "title": "结构物变形趋势异常研判与复核流程",
        "url": "https://kb.rail.local/sop/anomaly-review",
        "summary": "沉降/位移趋势异常的复核、分级研判与专家会商流程。",
        "source": "案例库",
        "tags": "异常,趋势,anomaly,变形,研判,沉降",
        "content": "趋势突变须 24h 内加密观测，结合历史基线判断是否启动应急预案。",
    },
    {
        "title": "风险指数预测性预警响应预案",
        "url": "https://kb.rail.local/sop/forecast-response",
        "summary": "基于风险指数外推的预测性预警的分级响应与资源预置。",
        "source": "案例库",
        "tags": "预测,预警,forecast,risk_index,趋势外推,响应",
        "content": "预测级别达「高」应提前预置巡查力量，并对重点区段下发风险提示。",
    },
    {
        "title": "涉铁工程应急预案通用模板",
        "url": "https://kb.rail.local/templates/emergency-plan",
        "summary": "应急预案通用结构：组织机构、响应分级、处置流程与后期处置。",
        "source": "手册",
        "tags": "应急预案,通用,处置,模板,响应分级",
        "content": "预案应包含指挥体系、预警发布、现场处置、信息报送与恢复评估五部分。",
    },
    {
        "title": "高速铁路工务安全规则（摘录）",
        "url": "https://kb.rail.local/standards/gongwu-safety",
        "summary": "工务作业安全、防护设置与列车放行条件的核心条款摘录。",
        "source": "规范库",
        "tags": "工务,安全,规范,防护,放行",
        "content": "未设好防护不准开工；慢行与封锁需调度命令，放行列车前确认设备状态。",
    },
    {
        "title": "现场急救与信息上报流程",
        "url": "https://kb.rail.local/sop/first-aid-report",
        "summary": "人员伤害现场急救要点与逐级信息上报时限要求。",
        "source": "内训库",
        "tags": "急救,上报,处置,人员伤害,时限",
        "content": "先抢救后处置，10 分钟内口头上报、1 小时内书面报告，保护现场证据。",
    },
    {
        "title": "处置预案与知识库关联检索说明",
        "url": "https://kb.rail.local/help/playbook-kb",
        "summary": "说明处置预案如何按「项目×类型×级别」匹配，并自动检索关联知识库链接。",
        "source": "手册",
        "tags": "知识库,处置预案,关联,检索,知识库联动",
        "content": "告警处置时系统自动按告警上下文检索知识库，给出最相关的规范与 SOP 链接。",
    },
]


def seed_knowledge() -> dict:
    """幂等播种 mock 知识库条目。返回 {created, skipped}。"""
    created = 0
    skipped = 0
    db = SessionLocal()
    try:
        for a in _ARTICLES:
            exists = db.scalar(
                select(KnowledgeArticle.id).where(
                    KnowledgeArticle.is_deleted.is_(False),
                    KnowledgeArticle.title == a["title"],
                )
            )
            if exists:
                skipped += 1
                continue
            db.add(
                KnowledgeArticle(
                    title=a["title"],
                    url=a["url"],
                    summary=a["summary"],
                    source=a["source"],
                    tags=a["tags"],
                    content=a.get("content"),
                    enabled=True,
                )
            )
            created += 1
        db.commit()
    finally:
        db.close()
    return {"created": created, "skipped": skipped}
