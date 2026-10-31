"""Descoberta automática de modelos (fixtures, sem rede real)."""
import httpx
import pytest

from ai_bridge import bridge as bridge_mod
from ai_bridge import config, discovery


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError('no json')
        return self._payload


def test_parse_openai_and_anthropic_payloads():
    openai = {'data': [{'id': 'gpt-4o'}, {'id': 'o3-mini'}]}
    anthropic = {'data': [{'id': 'claude-sonnet-5', 'display_name': 'Claude Sonnet 5'}]}
    assert [m['id'] for m in discovery._parse_models(openai)] == ['gpt-4o', 'o3-mini']
    assert discovery._parse_models(anthropic)[0]['label'] == 'Claude Sonnet 5'


def test_free_classification():
    assert discovery.classify_free('OpenRouter', 'meta-llama/llama-3:free', 'https://openrouter.ai/api/v1')
    assert discovery.classify_free('LiteLLM', 'free-gemma-4-31b', 'http://127.0.0.1:4000/v1')
    assert discovery.classify_free('Ollama', 'qwen3:8b', 'http://localhost:11434/v1')
    assert not discovery.classify_free('OpenAI', 'gpt-4o', 'https://api.openai.com/v1')


def test_fetch_models_parses_and_sorts(monkeypatch):
    calls = {}

    def fake_get(url, headers=None, timeout=None):
        calls['url'] = url
        calls['headers'] = headers
        return FakeResponse(payload={'data': [
            {'id': 'zeta'}, {'id': 'alpha:free'}, {'id': 'beta'},
        ]})

    monkeypatch.setattr(discovery.httpx, 'get', fake_get)
    result = discovery.fetch_models('https://api.example.com/v1', {'Authorization': 'Bearer k'}, 'X')

    assert calls['url'] == 'https://api.example.com/v1/models'
    assert result['ok'] is True
    assert [m['id'] for m in result['models']] == ['alpha:free', 'beta', 'zeta']
    assert result['free_count'] == 1
    assert result['models'][0]['free'] is True


def test_fetch_models_reports_http_error(monkeypatch):
    monkeypatch.setattr(discovery.httpx, 'get',
                        lambda *a, **k: FakeResponse(status_code=401, text='unauthorized'))
    result = discovery.fetch_models('https://api.example.com/v1', {})
    assert result['ok'] is False
    assert '401' in result['error']


def test_fetch_models_requires_base_url():
    assert discovery.fetch_models('', {})['ok'] is False


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(bridge_mod.Bridge, '_sync_connected_targets', lambda self: None)
    return bridge_mod.Bridge()


def test_bridge_fetch_models_uses_provider_env_key(bridge, monkeypatch):
    monkeypatch.setenv('AI_BRIDGE_DISCOVERY_KEY', 'env-key')
    monkeypatch.setattr(discovery.httpx, 'get', lambda url, headers=None, timeout=None: FakeResponse(
        payload={'data': [{'id': 'm1'}, {'id': 'm2:free'}]}))
    monkeypatch.setattr(config, 'get_provider', lambda name: {
        'name': 'Mimo', 'base_url': 'https://api.example.com/v1', 'api_key': '',
        'env_key': 'AI_BRIDGE_DISCOVERY_KEY', 'models': [],
    })

    res = bridge.fetch_models('Mimo')

    assert res['ok'] is True
    assert res['total'] == 2
    assert res['free_count'] >= 1


def test_bridge_fetch_models_adhoc_anthropic_uses_x_api_key(bridge, monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured['headers'] = headers
        return FakeResponse(payload={'data': [{'id': 'claude-sonnet-5'}]})

    monkeypatch.setattr(discovery.httpx, 'get', fake_get)

    res = bridge.fetch_models('', 'https://api.anthropic.com/v1', 'sk-ant', '', None)

    assert res['ok'] is True
    assert 'x-api-key' in captured['headers']
    assert captured['headers']['x-api-key'] == 'sk-ant'
    assert 'Authorization' not in captured['headers']

def test_bridge_fetch_models_codex_oauth_has_friendly_error(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: {
        'name': 'Codex (OAuth)', 'base_url': '', 'api_key': '',
        'auth': {'kind': 'oauth', 'source': 'codex'}, 'models': [],
    })
    res = bridge.fetch_models('Codex (OAuth)')
    assert res['ok'] is False
    assert '/models' in res['error']


def test_fetch_models_drops_empty_headers(monkeypatch):
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured['headers'] = headers
        return FakeResponse(payload={'data': [{'id': 'm'}]})

    monkeypatch.setattr(discovery.httpx, 'get', fake_get)
    result = discovery.fetch_models('https://x.example/v1',
                                    {'Authorization': 'Bearer ', 'Content-Type': 'application/json'})
    assert result['ok'] is True
    assert 'Authorization' not in captured['headers']
    assert captured['headers']['Content-Type'] == 'application/json'
