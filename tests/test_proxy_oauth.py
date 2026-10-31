"""Proxy routing for OAuth providers: protocol selection and token refresh on 401."""
import json
from unittest.mock import MagicMock

import httpx
import pytest

from ai_bridge import oauth
from ai_bridge.proxy import app as proxy_app

OAUTH_PROVIDER = {
    'name': 'Codex',
    'base_url': '',
    'api_key': '',
    'auth': {'kind': 'oauth', 'source': 'codex'},
    'models': [{'id': 'gpt-6-luna', 'label': 'GPT-6 Luna'}],
}


@pytest.fixture
def client():
    proxy_app.config['TESTING'] = True
    with proxy_app.test_client() as c:
        yield c


@pytest.fixture
def passthrough(monkeypatch):
    """Point the route at an OAuth provider and a fake resolved auth."""
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model',
                        lambda model: OAUTH_PROVIDER)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id',
                        lambda model: model.split('/', 1)[1] if '/' in model else model)
    auth = oauth.ResolvedAuth(
        headers={'Authorization': 'Bearer token-123', 'chatgpt-account-id': 'acc-9',
                 'Content-Type': 'application/json'},
        base_url='https://upstream.example/v1',
        protocol='responses',
        source='codex',
        account_id='acc-9',
    )
    monkeypatch.setattr('ai_bridge.proxy._resolve', lambda provider, force_refresh=False: auth)
    return auth


def test_responses_passthrough_keeps_wire_format(client, passthrough, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, body=json, headers=headers)
        return httpx.Response(200, json={'id': 'resp_1', 'object': 'response',
                                         'output': [{'type': 'message', 'content': []}]})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)

    resp = client.post('/v1/responses', json={
        'model': 'Codex/gpt-6-luna',
        'input': 'oi',
        'tools': [{'type': 'function', 'name': 'shell'}],
    })

    assert resp.status_code == 200
    assert captured['url'] == 'https://upstream.example/v1/responses'
    assert captured['body']['model'] == 'gpt-6-luna'
    assert captured['body']['input'] == 'oi'
    assert captured['body']['tools'][0]['name'] == 'shell'
    assert captured['headers']['chatgpt-account-id'] == 'acc-9'


def test_responses_stream_is_forwarded_byte_for_byte(client, passthrough, monkeypatch):
    class FakeStream:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            yield b'event: response.completed\ndata: {"type":"response.completed"}\n\n'

    monkeypatch.setattr('ai_bridge.proxy.httpx.stream',
                        lambda *a, **k: FakeStream())

    resp = client.post('/v1/responses', json={
        'model': 'Codex/gpt-6-luna', 'input': 'oi', 'stream': True,
    })

    assert resp.status_code == 200
    assert resp.get_data(as_text=True).startswith('event: response.completed')


def test_messages_passthrough_for_anthropic_provider(client, monkeypatch):
    provider = {
        'name': 'Claude', 'base_url': '', 'api_key': '',
        'auth': {'kind': 'oauth', 'source': 'claude'},
        'models': [{'id': 'claude-sonnet-5', 'label': 'Sonnet'}],
    }
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model', lambda model: provider)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id',
                        lambda model: model.split('/', 1)[1] if '/' in model else model)
    auth = oauth.ResolvedAuth(headers={'Authorization': 'Bearer c-token'},
                              base_url='https://api.anthropic.com/v1',
                              protocol='anthropic', source='claude')
    monkeypatch.setattr('ai_bridge.proxy._resolve', lambda provider, force_refresh=False: auth)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, body=json, headers=headers)
        return httpx.Response(200, json={'id': 'msg_1', 'type': 'message',
                                         'content': [{'type': 'text', 'text': 'oi'}]})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)

    resp = client.post('/v1/messages', json={
        'model': 'Claude/claude-sonnet-5', 'max_tokens': 16,
        'messages': [{'role': 'user', 'content': 'oi'}],
    })

    assert resp.status_code == 200
    assert captured['url'] == 'https://api.anthropic.com/v1/messages'
    assert captured['body']['model'] == 'claude-sonnet-5'
    assert captured['body']['messages'][0]['content'] == 'oi'


def test_missing_credentials_returns_actionable_401(client, monkeypatch):
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model', lambda model: OAUTH_PROVIDER)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id', lambda model: 'gpt-6-luna')

    def boom(provider, force_refresh=False):
        raise oauth.MissingCredentials('Codex', 'codex', 'Rode `codex login`.')

    monkeypatch.setattr('ai_bridge.proxy._resolve', boom)

    resp = client.post('/v1/responses', json={'model': 'Codex/gpt-6-luna', 'input': 'oi'})

    assert resp.status_code == 401
    body = resp.get_json()
    assert 'codex login' in body['error']['message']


def test_oauth_provider_retries_once_after_401(client, monkeypatch):
    stale = oauth.ResolvedAuth(headers={'Authorization': 'Bearer stale'},
                               base_url='https://upstream.example/v1',
                               protocol='chat', source='codex')
    fresh = oauth.ResolvedAuth(headers={'Authorization': 'Bearer fresh'},
                               base_url='https://upstream.example/v1',
                               protocol='chat', source='codex')
    calls = {'n': 0, 'headers': None}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return httpx.Response(401, json={'error': 'expired'})
        calls['headers'] = headers
        return httpx.Response(200, json={
            'id': 'chatcmpl-1', 'object': 'chat.completion',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': 'ok'}}],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        })

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model', lambda m: OAUTH_PROVIDER)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id', lambda m: 'gpt-6-luna')
    monkeypatch.setattr('ai_bridge.proxy._resolve',
                        lambda provider, force_refresh=False: fresh if force_refresh else stale)

    resp = client.post('/v1/responses', json={'model': 'Codex/gpt-6-luna', 'input': 'oi'})

    assert resp.status_code == 200
    assert calls['n'] == 2
    assert calls['headers']['Authorization'] == 'Bearer fresh'

def test_responses_passthrough_retries_after_401(client, monkeypatch):
    """Passthrough de Responses também renova o token e repete uma vez."""
    stale = oauth.ResolvedAuth(headers={'Authorization': 'Bearer stale'},
                               base_url='https://upstream.example/v1',
                               protocol='responses', source='codex')
    fresh = oauth.ResolvedAuth(headers={'Authorization': 'Bearer fresh'},
                               base_url='https://upstream.example/v1',
                               protocol='responses', source='codex')
    calls = {'n': 0, 'headers': None}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls['n'] += 1
        if calls['n'] == 1:
            return httpx.Response(401, json={'error': 'expired'})
        calls['headers'] = headers
        return httpx.Response(200, json={'id': 'resp_ok', 'object': 'response', 'output': []})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model', lambda m: OAUTH_PROVIDER)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id', lambda m: 'gpt-6-luna')
    monkeypatch.setattr('ai_bridge.proxy._resolve',
                        lambda provider, force_refresh=False: fresh if force_refresh else stale)

    resp = client.post('/v1/responses', json={'model': 'Codex/gpt-6-luna', 'input': 'oi'})

    assert resp.status_code == 200
    assert calls['n'] == 2
    assert calls['headers']['Authorization'] == 'Bearer fresh'

def test_responses_passthrough_defaults_store_false(client, passthrough, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured['body'] = json
        return httpx.Response(200, json={'id': 'r1', 'object': 'response', 'output': []})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)

    resp = client.post('/v1/responses', json={'model': 'Codex/gpt-6-luna', 'input': 'oi'})

    assert resp.status_code == 200
    assert captured['body']['store'] is False


def test_responses_passthrough_keeps_explicit_store(client, passthrough, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured['body'] = json
        return httpx.Response(200, json={'id': 'r2', 'object': 'response', 'output': []})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)

    client.post('/v1/responses', json={'model': 'Codex/gpt-6-luna', 'input': 'oi', 'store': True})

    assert captured['body']['store'] is True

def test_responses_passthrough_does_not_inject_store_for_other_providers(client, monkeypatch):
    provider = {'name': 'DS', 'base_url': '', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'deepseek'},
                'models': [{'id': 'm', 'label': 'M'}]}
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_provider_for_model', lambda m: provider)
    monkeypatch.setattr('ai_bridge.proxy.cfg.get_model_id', lambda m: 'm')
    auth = oauth.ResolvedAuth(headers={'Authorization': 'Bearer t'},
                              base_url='https://api.deepseek.com/v1',
                              protocol='responses', source='deepseek')
    monkeypatch.setattr('ai_bridge.proxy._resolve', lambda p, force_refresh=False: auth)
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured['body'] = json
        return httpx.Response(200, json={'id': 'r3', 'object': 'response', 'output': []})

    monkeypatch.setattr('ai_bridge.proxy.httpx.post', fake_post)

    resp = client.post('/v1/responses', json={'model': 'DS/m', 'input': 'oi'})

    assert resp.status_code == 200
    assert 'store' not in captured['body']
