"""Bridge/UI-facing OAuth surface: provider CRUD, status and login URL."""
import types

import pytest

from ai_bridge import bridge as bridge_mod
from ai_bridge import config, oauth


OAUTH_PROVIDER = {
    'name': 'Codex',
    'base_url': '',
    'api_key': '',
    'auth': {'kind': 'oauth', 'source': 'codex'},
    'protocol': 'responses',
    'models': [{'id': 'gpt-6-luna', 'label': 'GPT-6 Luna'}],
}


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(bridge_mod.Bridge, '_sync_connected_targets', lambda self: None)
    monkeypatch.setattr(bridge_mod, 'claude_code', types.SimpleNamespace(is_connected=lambda: False))
    monkeypatch.setattr(bridge_mod, 'claude_desktop', types.SimpleNamespace(is_connected=lambda: False))
    monkeypatch.setattr(bridge_mod, 'codex_mod', types.SimpleNamespace(is_connected=lambda: False))
    return bridge_mod.Bridge()


def test_add_provider_oauth_does_not_require_api_key(bridge, monkeypatch):
    captured = {}
    monkeypatch.setattr(config, 'add_provider',
                        lambda *args, **kwargs: captured.update(args=args, kwargs=kwargs))

    res = bridge.add_provider('Codex', '', '', 'gpt-6-luna|GPT-6 Luna',
                              {'kind': 'oauth', 'source': 'codex'}, 'responses')

    assert res['ok'] is True
    args = captured['args']
    assert args[0] == 'Codex'
    assert args[2] == ''  # sem chave
    assert captured['kwargs']['auth'] == {'kind': 'oauth', 'source': 'codex'}
    assert captured['kwargs']['protocol'] == 'responses'


def test_add_provider_rejects_unknown_oauth_source(bridge):
    res = bridge.add_provider('X', '', '', 'm', {'kind': 'oauth', 'source': 'nope'})
    assert res['ok'] is False
    assert 'desconhecida' in res['error']


def test_add_provider_api_key_still_requires_key(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_providers', lambda: [])
    monkeypatch.setattr(config, 'add_provider',
                        lambda *a, **k: pytest.fail('não deveria salvar sem chave'))
    res = bridge.add_provider('DeepSeek', 'https://api.deepseek.com/v1', '', 'deepseek-chat')
    assert res['ok'] is False
    assert 'Chave de API' in res['error']


def test_get_provider_detail_exposes_auth_without_token(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_providers', lambda: [{**OAUTH_PROVIDER, 'api_key': ''}])
    monkeypatch.setattr(config, 'get_api_key', lambda name: '')
    monkeypatch.setattr(oauth, 'status', lambda provider: {
        'kind': 'oauth', 'source': 'codex', 'connected': True, 'account_id': 'acc',
    })

    detail = bridge.get_provider_detail('Codex')

    assert detail['ok'] is True
    assert detail['auth'] == {'kind': 'oauth', 'source': 'codex'}
    assert detail['protocol'] == 'responses'
    assert detail['auth_status']['connected'] is True
    assert 'access_token' not in str(detail)


def test_test_provider_validates_oauth_session(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: OAUTH_PROVIDER)
    monkeypatch.setattr(oauth, 'resolve', lambda provider, force_refresh=False: oauth.ResolvedAuth(
        headers={'Authorization': 'Bearer x'}, base_url='https://chatgpt.com/backend-api/codex',
        protocol='responses', source='codex', account_id='acc-1'))

    res = bridge.test_provider('', '', 'Codex')

    assert res['ok'] is True
    assert res['oauth'] is True
    assert res['protocol'] == 'responses'
    assert res['account_id'] == 'acc-1'


def test_test_provider_reports_missing_session(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: OAUTH_PROVIDER)

    def boom(provider, force_refresh=False):
        raise oauth.MissingCredentials('Codex', 'codex', 'Rode `codex login`.')

    monkeypatch.setattr(oauth, 'resolve', boom)

    res = bridge.test_provider('', '', 'Codex')

    assert res['ok'] is False
    assert res['auth_required'] is True
    assert 'codex login' in res['error']


def test_get_oauth_login_url_opens_browser(bridge, monkeypatch):
    opened = {}
    monkeypatch.setattr(config, 'get_provider', lambda name: OAUTH_PROVIDER)
    monkeypatch.setattr(bridge_mod.proxy, 'get_port', lambda: 38771)
    monkeypatch.setattr(bridge_mod.oauth_login, 'begin', lambda provider, redirect: {
        'url': 'https://auth.openai.com/oauth/authorize?x=1', 'state': 'st', 'source': 'codex',
    })
    monkeypatch.setattr(bridge_mod.webbrowser, 'open', lambda url: opened.update(url=url))

    res = bridge.get_oauth_login_url('Codex')

    assert res['ok'] is True
    assert res['redirect_uri'] == 'http://127.0.0.1:38771/oauth/callback'
    assert opened['url'].startswith('https://auth.openai.com/oauth/authorize')


def test_get_oauth_login_url_rejects_api_key_provider(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider',
                        lambda name: {'name': 'DeepSeek', 'api_key': 'k', 'models': []})
    res = bridge.get_oauth_login_url('DeepSeek')
    assert res['ok'] is False


def test_presets_include_oauth_sources(bridge):
    presets = bridge.get_presets()['presets']
    oauth_presets = [p for p in presets if (p.get('auth') or {}).get('kind') == 'oauth']
    assert {p['auth']['source'] for p in oauth_presets} >= {'codex', 'claude', 'gemini', 'huggingface'}

def test_reauth_oauth_renews_session(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: OAUTH_PROVIDER)
    monkeypatch.setattr(oauth, 'resolve', lambda provider, force_refresh=False: oauth.ResolvedAuth(
        headers={'Authorization': 'Bearer renewed'},
        base_url='https://chatgpt.com/backend-api/codex',
        protocol='responses', source='codex', account_id='acc-1'))

    res = bridge.reauth_oauth('Codex')

    assert res['ok'] is True
    assert res['renewed'] is True
    assert res['source'] == 'codex'
    assert res['account_id'] == 'acc-1'


def test_reauth_falls_back_to_browser_login(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: OAUTH_PROVIDER)

    def boom(provider, force_refresh=False):
        raise oauth.MissingCredentials('Codex', 'codex', 'faça login')

    monkeypatch.setattr(oauth, 'resolve', boom)
    monkeypatch.setattr(bridge_mod.proxy, 'get_port', lambda: 38771)
    monkeypatch.setattr(bridge_mod.oauth_login, 'begin', lambda provider, redirect: {
        'url': 'https://auth.openai.com/oauth/authorize?x=1', 'state': 's', 'source': 'codex',
    })
    monkeypatch.setattr(bridge_mod.webbrowser, 'open', lambda url: None)

    res = bridge.reauth_oauth('Codex')

    assert res['ok'] is True
    assert res['url'].startswith('https://auth.openai.com/oauth/authorize')
    assert 'login aberto' in res['message'].lower()


def test_reauth_rejects_api_key_provider(bridge, monkeypatch):
    monkeypatch.setattr(config, 'get_provider', lambda name: {
        'name': 'DeepSeek', 'api_key': 'k', 'models': [],
    })
    res = bridge.reauth_oauth('DeepSeek')
    assert res['ok'] is False
    assert 'OAuth' in res['error']

def test_add_provider_oauth_requires_base_url_when_source_has_no_default(bridge):
    res = bridge.add_provider('Cloudflare', '', '', 'm',
                              {'kind': 'oauth', 'source': 'cloudflare'})
    assert res['ok'] is False
    assert 'base_url' in res['error']
