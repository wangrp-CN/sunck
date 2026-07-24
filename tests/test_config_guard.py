"""生产环境配置护栏测试。"""

import pytest

from app.config import assert_production_safe, settings


def test_prod_rejects_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "change-me-to-a-long-random-string")
    monkeypatch.setattr(settings, "cors_origins", "https://ok.example.com")
    monkeypatch.setattr(settings, "debug", False)
    with pytest.raises(RuntimeError):
        assert_production_safe()


def test_prod_rejects_wildcard_cors(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "a-good-random-key-1234567890abcdef")
    monkeypatch.setattr(settings, "cors_origins", "*")
    monkeypatch.setattr(settings, "debug", False)
    with pytest.raises(RuntimeError):
        assert_production_safe()


def test_prod_ok_with_safe_values(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "secret_key", "a-good-random-key-1234567890abcdef")
    monkeypatch.setattr(settings, "cors_origins", "https://ok.example.com")
    monkeypatch.setattr(settings, "debug", False)
    assert_production_safe()  # 不应抛异常


def test_non_prod_bypasses_guard(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "secret_key", "change-me-to-a-long-random-string")
    monkeypatch.setattr(settings, "cors_origins", "*")
    monkeypatch.setattr(settings, "debug", True)
    assert_production_safe()  # 非生产环境不校验
