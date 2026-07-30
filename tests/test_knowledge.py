"""🅱 知识库自动检索关联链接 测试。

覆盖：检索相关性打分（标题命中优先）、CRUD（API 层）、
按告警上下文的关联链接检索端点（/v1/playbooks/suggest-references）、
以及 recommend 响应自动附加 suggested_references。

隔离约定：自建知识条目在 finally 中清理；复用系统预置的 6 类预案与 10 条知识库。
"""

import secrets

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.database import SessionLocal
from app.model.knowledge import KnowledgeArticle


def _uid() -> str:
    return secrets.token_hex(3)


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _first_pid(db) -> int:
    from app.model.project import Project

    pid = db.scalars(select(Project.id).where(Project.is_deleted.is_(False))).first()
    assert pid is not None, "需存在真实项目"
    return pid


def test_knowledge_search_and_crud(client: TestClient, admin_token: str):
    db = SessionLocal()
    created: list[int] = []
    try:
        tok = _uid()
        # 创建两条：一条标题含唯一关键词（应被检索置顶），一条普通
        r1 = client.post(
            "/api/v1/knowledge/",
            headers=_h(admin_token),
            json={
                "title": f"ZZ{tok}围栏越界专项处置规程",
                "url": f"https://kb.rail.local/{tok}/fence",
                "summary": "围栏越界现场处置与上报。",
                "source": "内训库",
                "tags": f"围栏,侵入,{tok}",
                "content": "围栏越界须立即下道。",
            },
        )
        assert r1.status_code == 200 and r1.json()["code"] == 0
        created.append(r1.json()["data"]["id"])

        r2 = client.post(
            "/api/v1/knowledge/",
            headers=_h(admin_token),
            json={
                "title": f"通用巡检记录表{tok}",
                "url": f"https://kb.rail.local/{tok}/patrol",
                "summary": "日常巡检记录。",
                "source": "手册",
                "tags": f"巡检,{tok}",
            },
        )
        assert r2.status_code == 200 and r2.json()["code"] == 0
        created.append(r2.json()["data"]["id"])

        # 检索：唯一关键词应命中且置顶
        r = client.get(f"/api/v1/knowledge/search?q=ZZ{tok}围栏越界", headers=_h(admin_token))
        assert r.status_code == 200 and r.json()["code"] == 0
        items = r.json()["data"]
        assert items, "检索应返回结果"
        assert items[0]["id"] == created[0], "标题精确命中的条目应置顶"
        assert items[0]["score"] > 0

        # 列表 + 过滤
        r = client.get("/api/v1/knowledge/", headers=_h(admin_token), params={"source": "内训库"})
        assert r.status_code == 200
        assert r.json()["data"]["total"] >= 1

        # 编辑
        r = client.put(
            f"/api/v1/knowledge/{created[0]}",
            headers=_h(admin_token),
            json={"summary": "已更新要点"},
        )
        assert r.status_code == 200 and r.json()["data"]["summary"] == "已更新要点"

        # 删除后不可见
        r = client.delete(f"/api/v1/knowledge/{created[0]}", headers=_h(admin_token))
        assert r.status_code == 200 and r.json()["code"] == 0
        r = client.get(f"/api/v1/knowledge/{created[0]}", headers=_h(admin_token))
        assert r.json()["code"] == 404
    finally:
        # 清理（若前面断言失败未删除）
        for kid in created:
            obj = db.get(KnowledgeArticle, kid)
            if obj:
                obj.is_deleted = True
        db.commit()
        db.close()


def test_suggest_references_endpoint(client: TestClient, admin_token: str):
    """按告警类型检索关联知识库链接；recommend 响应应自动附带 suggested_references。"""
    # 围栏侵入场景：预置知识库含「防护栅栏」条目（tag=fence_intrusion），应被关联
    r = client.post(
        "/api/v1/playbooks/suggest-references",
        headers=_h(admin_token),
        json={"alarm_type": "fence_intrusion", "limit": 5},
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    refs = r.json()["data"]
    assert isinstance(refs, list) and len(refs) > 0, "应检索到关联知识库链接"
    titles = [x["title"] for x in refs]
    assert any("栅栏" in t for t in titles), f"应关联到围栏知识条目，实际：{titles}"

    # recommend 自动附带 suggested_references
    r = client.get(
        "/api/v1/playbooks/recommend",
        headers=_h(admin_token),
        params={"alarm_type": "fence_intrusion", "limit": 5},
    )
    assert r.status_code == 200 and r.json()["code"] == 0
    pbs = r.json()["data"]
    assert pbs, "应推荐到围栏预案"
    assert "suggested_references" in pbs[0], "recommend 响应应含 suggested_references"
    assert any(
        "栅栏" in x["title"] for x in pbs[0]["suggested_references"]
    ), "推荐预案应自动关联知识库链接"
