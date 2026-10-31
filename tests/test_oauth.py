"""OAuth credential sources + PKCE tests (no real secrets, fixtures only)."""
import base64
import json
import time

import httpx
import pytest

from ai_bridge import oauth


def _jwt(exp: float, extra: dict | None = None) -> str:
    payload = {'exp': int(exp), 'sub': 'test'}
    if extra:
        payload.update(extra)
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
    return f'eyJhbGciOiJub25lIn0.{body}.sig'


@pytest.fixture(autouse=True)
def _clear_cache():
    oauth._CACHE.clear()
    yield
    oauth._CACHE.clear()


@pytest.fixture
def codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path))
    return tmp_path


def _write_codex_auth(home, access, refresh='rt-old', account='acc-123'):
    (home / 'auth.json').write_text(json.dumps({
        'auth_mode': 'chatgpt',
        'tokens': {
            'access_token': access,
            'refresh_token': refresh,
            'id_token': 'idt',
            'account_id': account,
        },
        'last_refresh': '2026-01-01T00:00:00Z',
    }), 'utf-8')


def _codex_provider(name='Codex'):
    return {
        'name': name,
        'base_url': '',
        'api_key': '',
        'auth': {'kind': 'oauth', 'source': 'codex'},
        'models': [{'id': 'gpt-6-luna', 'label': 'GPT-6 Luna'}],
    }


def test_codex_source_loads_cli_session(codex_home):
    _write_codex_auth(codex_home, _jwt(time.time() + 3600))

    auth = oauth.resolve(_codex_provider())

    assert auth.protocol == 'responses'
    assert auth.base_url == 'https://chatgpt.com/backend-api/codex'
    assert auth.source == 'codex'
    assert auth.headers['Authorization'].startswith('Bearer ')
    assert auth.headers['chatgpt-account-id'] == 'acc-123'
    assert auth.headers['originator'] == 'codex_cli_rs'


def test_expired_codex_token_refreshes_and_writes_back(codex_home, monkeypatch):
    _write_codex_auth(codex_home, _jwt(time.time() - 60), refresh='rt-old')
    calls = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls['url'] = url
        calls['body'] = json
        return httpx.Response(200, json={
            'access_token': _jwt(time.time() + 3600),
            'refresh_token': 'rt-new',
            'expires_in': 3600,
            'id_token': 'idt-new',
        })

    monkeypatch.setattr(oauth.httpx, 'post', fake_post)

    auth = oauth.resolve(_codex_provider())

    assert calls['url'] == 'https://auth.openai.com/oauth/token'
    assert calls['body']['grant_type'] == 'refresh_token'
    assert calls['body']['refresh_token'] == 'rt-old'
    assert calls['body']['client_id'] == oauth.CodexSource.client_id
    saved = json.loads((codex_home / 'auth.json').read_text('utf-8'))
    assert saved['tokens']['refresh_token'] == 'rt-new'
    assert saved['tokens']['access_token'] == auth.headers['Authorization'].split(' ', 1)[1]
    assert saved['auth_mode'] == 'chatgpt'


def test_missing_session_raises_actionable_error(codex_home):
    with pytest.raises(oauth.MissingCredentials) as excinfo:
        oauth.resolve(_codex_provider())
    message = str(excinfo.value)
    assert 'Codex' in message
    assert 'codex login' in message


def test_api_key_provider_is_unchanged():
    auth = oauth.resolve({
        'name': 'DeepSeek',
        'base_url': 'https://api.deepseek.com/v1',
        'api_key': 'sk-test',
        'models': [],
    })
    assert auth.protocol == 'chat'
    assert auth.headers['Authorization'] == 'Bearer sk-test'
    assert auth.source == 'api_key'


def test_status_never_leaks_token(codex_home):
    _write_codex_auth(codex_home, _jwt(time.time() + 3600))
    status = oauth.status(_codex_provider())
    assert status['connected'] is True
    assert status['source'] == 'codex'
    assert status['account_id'] == 'acc-123'
    serialized = json.dumps(status)
    assert 'eyJ' not in serialized  # nenhum JWT no payload do UI


def test_pkce_pair_is_s256():
    verifier, challenge = oauth.new_pkce_pair()
    assert len(verifier) >= 43
    assert '=' not in challenge
    url = oauth.authorize_url(oauth.SOURCES['codex'], 'http://127.0.0.1:5555/callback', 'st',
                              challenge=challenge)
    assert url.startswith('https://auth.openai.com/oauth/authorize?')
    assert 'code_challenge_method=S256' in url
    assert 'code_challenge=' in url
    assert oauth.CodexSource.client_id in url


def test_gemini_authorize_url_has_offline_access():
    src = oauth.SOURCES['gemini']
    url = oauth.authorize_url(src, 'http://127.0.0.1:5555/callback', 'st',
                              client_id='cid.apps.googleusercontent.com', challenge='x')
    assert 'accounts.google.com' in url
    assert 'access_type=offline' in url
    assert 'prompt=consent' in url


def test_exchange_code_persists_session(codex_home, monkeypatch):
    def fake_post(url, json=None, timeout=None, headers=None):
        return httpx.Response(200, json={
            'access_token': _jwt(time.time() + 3600),
            'refresh_token': 'rt-from-code',
            'expires_in': 3600,
        })

    monkeypatch.setattr(oauth.httpx, 'post', fake_post)
    token = oauth.exchange_code(oauth.SOURCES['codex'], code='abc', verifier='ver',
                                redirect_uri='http://127.0.0.1:5555/callback')
    assert token.refresh_token == 'rt-from-code'
    saved = json.loads((codex_home / 'auth.json').read_text('utf-8'))
    assert saved['auth_mode'] == 'chatgpt'
    assert saved['tokens']['refresh_token'] == 'rt-from-code'
    assert saved['tokens']['access_token'] == token.access_token


def test_claude_session_uses_anthropic_passthrough(tmp_path, monkeypatch):
    creds = tmp_path / 'claude-creds.json'
    monkeypatch.setenv('AI_BRIDGE_CLAUDE_CREDENTIALS', str(creds))
    creds.write_text(json.dumps({'claudeAiOauth': {
        'accessToken': _jwt(time.time() + 3600),
        'refreshToken': 'c-rt',
        'expiresAt': int((time.time() + 3600) * 1000),
        'subscriptionType': 'max',
    }}), 'utf-8')
    provider = {'name': 'Claude', 'base_url': '', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'claude'}, 'models': []}

    auth = oauth.resolve(provider)

    assert auth.protocol == 'anthropic'
    assert auth.base_url == 'https://api.anthropic.com/v1'
    assert auth.headers['anthropic-beta'] == 'oauth-2025-04-20'

def test_gcloud_adc_refreshes_on_first_use(tmp_path, monkeypatch):
    adc = tmp_path / 'adc.json'
    adc.write_text(json.dumps({
        'type': 'authorized_user', 'client_id': 'cid-1', 'client_secret': 'sec-1',
        'refresh_token': 'g-rt',
    }), 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_GCLOUD_ADC', str(adc))
    calls = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.update(url=url, body=json)
        return httpx.Response(200, json={'access_token': 'g-at', 'expires_in': 3600})

    monkeypatch.setattr(oauth.httpx, 'post', fake_post)
    provider = {'name': 'GCloud', 'base_url': 'https://x.example/v1', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'gcloud'}, 'models': []}

    auth = oauth.resolve(provider)

    assert auth.headers['Authorization'] == 'Bearer g-at'
    assert calls['body']['client_id'] == 'cid-1'
    assert calls['body']['client_secret'] == 'sec-1'
    assert calls['body']['refresh_token'] == 'g-rt'
    assert 'scope' not in calls['body']  # Google recusa scope no refresh do ADC


def test_huggingface_token_file(tmp_path, monkeypatch):
    token_file = tmp_path / 'token'
    token_file.write_text('hf_abc123\n', 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_HF_TOKEN_FILE', str(token_file))
    provider = {'name': 'HF', 'base_url': '', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'huggingface'}, 'models': []}

    auth = oauth.resolve(provider)

    assert auth.headers['Authorization'] == 'Bearer hf_abc123'
    assert auth.base_url == 'https://router.huggingface.co/v1'
    assert auth.protocol == 'chat'


def test_copilot_reads_gh_hosts(tmp_path, monkeypatch):
    hosts = tmp_path / 'hosts.yml'
    hosts.write_text('github.com:\n    oauth_token: gho_xyz\n    user: alguem\n', 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_GH_HOSTS', str(hosts))
    monkeypatch.delenv('GH_TOKEN', raising=False)
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)
    provider = {'name': 'Copilot', 'base_url': '', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'copilot'}, 'models': []}

    auth = oauth.resolve(provider)

    assert auth.headers['Authorization'] == 'Bearer gho_xyz'
    assert auth.headers['Copilot-Integration-Id'] == 'vscode-chat'
    assert auth.base_url == 'https://api.githubcopilot.com'


def test_config_stores_oauth_provider_without_key(monkeypatch):
    from ai_bridge import config

    monkeypatch.setattr(config, '_set_key', lambda *a, **k: None)
    monkeypatch.setattr(config, '_delete_key', lambda *a, **k: None)
    saved = {}
    monkeypatch.setattr(config, 'load', lambda: saved if saved else {'providers': [], 'port': 1})
    monkeypatch.setattr(config, 'save', lambda data: saved.update(data))

    config.add_provider('Codex', '', '', [{'id': 'gpt-6-luna', 'label': 'GPT-6 Luna'}],
                        auth={'kind': 'oauth', 'source': 'codex'}, protocol='responses')

    entry = saved['providers'][0]
    assert entry['auth'] == {'kind': 'oauth', 'source': 'codex'}
    assert entry['protocol'] == 'responses'
    assert 'api_key' not in entry

def test_cloudflare_wrangler_token(tmp_path, monkeypatch):
    cfg = tmp_path / 'default.toml'
    cfg.write_text(
        'oauth_token = "cf-at"\n'
        'refresh_token = "cf-rt"\n'
        'expiration_time = "2999-01-01T00:00:00Z"\n'
        'scopes = "account:read user:read"\n',
        'utf-8',
    )
    monkeypatch.setenv('AI_BRIDGE_WRANGLER_CONFIG', str(cfg))
    provider = {
        'name': 'Cloudflare', 'api_key': '', 'auth': {'kind': 'oauth', 'source': 'cloudflare'},
        'base_url': 'https://api.cloudflare.com/client/v4/accounts/acc-1/ai/v1',
        'models': [],
    }

    auth = oauth.resolve(provider)

    assert auth.headers['Authorization'] == 'Bearer cf-at'
    assert auth.base_url.endswith('/accounts/acc-1/ai/v1')
    assert auth.protocol == 'chat'


def test_cloudflare_refreshes_and_rewrites_toml(tmp_path, monkeypatch):
    cfg = tmp_path / 'default.toml'
    cfg.write_text(
        'oauth_token = "cf-old"\n'
        'refresh_token = "cf-rt-old"\n'
        'expiration_time = "2000-01-01T00:00:00Z"\n'
        'scopes = "account:read"\n',
        'utf-8',
    )
    monkeypatch.setenv('AI_BRIDGE_WRANGLER_CONFIG', str(cfg))
    calls = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls.update(url=url, body=json)
        return httpx.Response(200, json={
            'access_token': 'cf-new', 'refresh_token': 'cf-rt-new', 'expires_in': 3600,
        })

    monkeypatch.setattr(oauth.httpx, 'post', fake_post)
    provider = {
        'name': 'Cloudflare', 'api_key': '', 'auth': {'kind': 'oauth', 'source': 'cloudflare'},
        'base_url': 'https://api.cloudflare.com/client/v4/accounts/acc-1/ai/v1',
        'models': [],
    }

    auth = oauth.resolve(provider)

    assert auth.headers['Authorization'] == 'Bearer cf-new'
    assert calls['url'] == 'https://dash.cloudflare.com/oauth2/token'
    text = cfg.read_text('utf-8')
    assert 'oauth_token = "cf-new"' in text
    assert 'refresh_token = "cf-rt-new"' in text
    assert 'scopes = "account:read"' in text  # preserva o que não é nosso

def test_oauth_source_without_default_base_url_requires_it(tmp_path, monkeypatch):
    cfg = tmp_path / 'default.toml'
    cfg.write_text('oauth_token = "cf-at"\nexpiration_time = "2999-01-01T00:00:00Z"\n', 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_WRANGLER_CONFIG', str(cfg))
    provider = {'name': 'Cloudflare', 'base_url': '', 'api_key': '',
                'auth': {'kind': 'oauth', 'source': 'cloudflare'}, 'models': []}

    with pytest.raises(oauth.ConfigurationError) as excinfo:
        oauth.resolve(provider)

    assert 'base_url' in str(excinfo.value)

def test_api_key_provider_can_use_env_var(monkeypatch):
    monkeypatch.setenv('AI_BRIDGE_ENV_KEY_TEST', 'env-secret')
    provider = {'name': 'Env', 'base_url': 'https://api.example.com/v1', 'api_key': '',
                'env_key': 'AI_BRIDGE_ENV_KEY_TEST', 'models': []}
    auth = oauth.resolve(provider)
    assert auth.headers['Authorization'] == 'Bearer env-secret'
    assert oauth.status(provider)['has_key'] is True


def test_api_key_provider_env_var_missing(monkeypatch):
    monkeypatch.delenv('AI_BRIDGE_ENV_KEY_MISSING', raising=False)
    provider = {'name': 'Env', 'base_url': 'https://api.example.com/v1', 'api_key': '',
                'env_key': 'AI_BRIDGE_ENV_KEY_MISSING', 'models': []}
    assert oauth.resolve(provider).headers['Authorization'] == 'Bearer '
    assert oauth.status(provider)['has_key'] is False
