"""CRUDService 基类单元测试（update / paginate 逻辑，不依赖真实 DB）。"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.model.system import User
from app.service.base import CRUDService


class _Svc(CRUDService):
    model = User


def _make_svc() -> tuple[_Svc, MagicMock]:
    db = MagicMock()
    return _Svc(db), db


def test_update_existing_sets_fields_and_commits():
    svc, db = _make_svc()
    obj = SimpleNamespace(name="old")
    db.get.return_value = obj
    res = svc.update(1, name="new", extra="ignored")
    assert res is obj
    assert obj.name == "new"
    assert not hasattr(obj, "extra")
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(obj)


def test_update_missing_returns_none():
    svc, db = _make_svc()
    db.get.return_value = None
    assert svc.update(999, name="x") is None
    db.commit.assert_not_called()


def test_paginate_returns_rows_and_total():
    svc, db = _make_svc()
    db.scalar.return_value = 42
    rows = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    db.scalars.return_value.all.return_value = rows
    result, total = svc.paginate(page=3, page_size=10)
    assert result == rows
    assert total == 42
    db.scalar.assert_called_once()
    db.scalars.assert_called_once()
