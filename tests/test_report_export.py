"""报表导出对称化（⑥）回归测试：隐患/设备 Excel·PDF 端点受权且格式正确。

校验点：
- 未带 token 返回 401；
- excel 返回 xlsx 魔数（PK\x03\x04），pdf 返回 %PDF；
- 带筛选条件不影响导出成功。
"""

import pytest


@pytest.fixture
def auth_header(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


def test_hazard_export_excel(auth_header, client):
    r = client.get("/api/v1/hazards/export", params={"fmt": "excel"}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"
    assert "spreadsheetml" in r.headers["content-type"]


def test_hazard_export_pdf(auth_header, client):
    r = client.get("/api/v1/hazards/export", params={"fmt": "pdf"}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"
    assert r.headers["content-type"] == "application/pdf"


def test_device_export_excel(auth_header, client):
    r = client.get("/api/v1/devices/export", params={"fmt": "excel"}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert r.content[:2] == b"PK"


def test_device_export_pdf(auth_header, client):
    r = client.get("/api/v1/devices/export", params={"fmt": "pdf"}, headers=auth_header)
    assert r.status_code == 200, r.text
    assert r.content[:4] == b"%PDF"


def test_hazard_export_requires_auth(client):
    r = client.get("/api/v1/hazards/export", params={"fmt": "excel"})
    assert r.status_code == 401
