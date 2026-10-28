"""Regression tests for provider validation in the desktop bridge."""
from unittest.mock import Mock

import httpx

from ai_bridge.bridge import Bridge


def test_test_provider_returns_model_count(monkeypatch):
    response = Mock()
    response.status_code = 200
    response.json.return_value = {
        "data": [{"id": "model-a"}, {"id": "model-b"}]
    }
    monkeypatch.setattr("ai_bridge.bridge.httpx.get", lambda *args, **kwargs: response)

    result = Bridge().test_provider("https://example.com/v1", "test-key")

    assert result["ok"] is True
    assert result["models"] == ["model-a", "model-b"]
    assert result["models_count"] == 2


def test_test_provider_requires_api_key():
    result = Bridge().test_provider("https://example.com/v1", "")

    assert result == {"ok": False, "error": "Chave API não informada."}


def test_test_provider_reports_actionable_401_without_exposing_key(monkeypatch):
    response = Mock()
    response.status_code = 401
    response.json.return_value = {
        "error": {"message": "invalid key bad-key"}
    }
    monkeypatch.setattr("ai_bridge.bridge.httpx.get", lambda *args, **kwargs: response)

    result = Bridge().test_provider("https://example.com/v1", "bad-key", "DeepSeek")

    assert result["ok"] is False
    assert result["status_code"] == 401
    assert "HTTP 401" in result["error"]
    assert "autenticação recusada" in result["error"]
    assert "bad-key" not in result["error"]
    assert "[chave ocultada]" in result["error"]


def test_test_provider_reports_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        request = httpx.Request("GET", "https://example.com/v1/models")
        raise httpx.TimeoutException("timeout", request=request)

    monkeypatch.setattr("ai_bridge.bridge.httpx.get", timeout)

    result = Bridge().test_provider("https://example.com/v1", "test-key")

    assert result == {"ok": False, "error": "Timeout ao conectar."}
