"""OAuth credentials for AI Bridge providers.

A provider can authenticate in two ways:

* **API key** (existing behaviour): the key lives in the OS keyring and is sent
  as ``Authorization: Bearer <key>`` to the provider ``base_url``.
* **OAuth** (new): the token comes from an OAuth session. The bridge first
  reuses the session a CLI already stored (``codex login``, ``claude``,
  ``gemini``) and refreshes it with the same token endpoint. When no session
  exists, ``ai_bridge.pkce`` starts the bridge's own PKCE/browser flow.

Providers opt in with::

    {"name": "Codex", "base_url": "...", "auth": {"kind": "oauth", "source": "codex"}}

``resolve()`` returns everything a route needs to talk to the upstream:
headers (with a valid bearer token), base URL and wire protocol
(``chat``, ``responses`` or ``anthropic``). Tokens are cached in memory and
written back to the CLI store after a refresh, so the CLI and the bridge stay
in sync and the user keeps a single session.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

try:  # Python 3.11+; usado apenas pelo adaptador do Wrangler
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    tomllib = None  # type: ignore[assignment]


log = logging.getLogger(__name__)

# Refresh a token slightly before it actually expires.
EXPIRY_SKEW_SECONDS = 90
USER_AGENT = 'ai-bridge/1.0.0'


class MissingCredentials(RuntimeError):
    """Raised when an OAuth provider has no usable session."""

    def __init__(self, provider_name: str, source: str, hint: str = ''):
        self.provider_name = provider_name
        self.source = source
        self.hint = hint
        message = (
            f'Sessão OAuth não encontrada para o provedor "{provider_name}" '
            f'(fonte: {source}).'
        )
        if hint:
            message += f' {hint}'
        super().__init__(message)


class ConfigurationError(MissingCredentials):
    """Raised when the provider is missing required configuration (ex.: base_url)."""



@dataclass
class Token:
    access_token: str
    refresh_token: str = ''
    expires_at: float = 0.0
    account_id: str = ''
    id_token: str = ''
    extra: dict = field(default_factory=dict)

    def expired(self, skew: float = EXPIRY_SKEW_SECONDS) -> bool:
        if not self.expires_at:
            return False
        return self.expires_at <= time.time() + skew


@dataclass
class ResolvedAuth:
    """Everything needed to reach the upstream for one request."""

    headers: dict
    base_url: str
    protocol: str
    source: str = 'api_key'
    account_id: str = ''
    refreshed: bool = False


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _jwt_exp(token: str) -> float:
    """Read ``exp`` from a JWT without verifying it (we only need scheduling)."""
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode('ascii')))
        exp = data.get('exp')
        return float(exp) if exp else 0.0
    except Exception:
        return 0.0


def _atomic_write(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.ai-bridge.tmp')
    tmp.write_text(json.dumps(data, indent=2), 'utf-8')
    if path.exists():
        try:
            os.chmod(tmp, path.stat().st_mode)
        except OSError:
            pass
    tmp.replace(path)


def _home(*parts: str) -> Path:
    return Path.home().joinpath(*parts)


# ─── Sources ───────────────────────────────────────────────────────────────────

class OAuthSource:
    """Common behaviour for providers authenticated with OAuth."""

    name = ''
    label = ''
    default_base_url = ''
    default_protocol = 'chat'
    token_url = ''
    client_id = ''
    client_secret = ''
    scope = ''
    login_hint = ''

    # -- storage ---------------------------------------------------------
    def credentials_path(self) -> Path:  # pragma: no cover - overridden
        raise NotImplementedError

    def load(self) -> Optional[Token]:  # pragma: no cover - overridden
        raise NotImplementedError

    def save(self, token: Token) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- wire ------------------------------------------------------------
    def headers(self, token: Token) -> dict:
        return {'Authorization': f'Bearer {token.access_token}'}

    def refresh_body(self, refresh_token: str, *, client_id: str, client_secret: str) -> dict:
        body = {'grant_type': 'refresh_token', 'refresh_token': refresh_token,
                'client_id': client_id}
        if client_secret:
            body['client_secret'] = client_secret
        if self.scope:
            body['scope'] = self.scope
        return body

    def default_client_id(self) -> str:
        return self.client_id

    def default_client_secret(self) -> str:
        return self.client_secret

    # -- token lifecycle --------------------------------------------------
    def refresh(self, token: Token, *, client_id: str = '', client_secret: str = '',
                token_url: str = '') -> Optional[Token]:
        if not token.refresh_token:
            return None
        url = token_url or self.token_url
        cid = client_id or self.default_client_id()
        secret = client_secret or self.default_client_secret()
        if not url or not cid:
            log.warning('%s: refresh sem token_url/client_id configurado', self.name)
            return None
        body = self.refresh_body(token.refresh_token, client_id=cid, client_secret=secret)
        try:
            resp = httpx.post(url, json=body, timeout=httpx.Timeout(20.0, read=60.0),
                              headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
        except httpx.HTTPError as exc:
            log.warning('%s: falha de rede ao renovar token: %s', self.name, exc)
            return None
        if resp.status_code != 200:
            log.warning('%s: refresh recusado (%s): %s', self.name, resp.status_code, resp.text[:200])
            return None
        try:
            payload = resp.json()
        except ValueError:
            return None
        access = payload.get('access_token') or ''
        if not access:
            return None
        expires_in = float(payload.get('expires_in') or 0)
        expires_at = time.time() + expires_in if expires_in else _jwt_exp(access)
        return Token(
            access_token=access,
            refresh_token=payload.get('refresh_token') or token.refresh_token,
            expires_at=expires_at,
            account_id=token.account_id,
            id_token=payload.get('id_token') or token.id_token,
            extra=token.extra,
        )


class CodexSource(OAuthSource):
    """Session written by ``codex login`` (ChatGPT account)."""

    name = 'codex'
    label = 'Codex / ChatGPT'
    default_base_url = 'https://chatgpt.com/backend-api/codex'
    default_protocol = 'responses'
    token_url = 'https://auth.openai.com/oauth/token'
    client_id = 'app_EMoamEEZ73f0CkXaXp7hrann'
    scope = 'openid profile email'
    login_hint = 'Rode `codex login` no terminal e tente novamente.'

    def credentials_path(self) -> Path:
        root = Path(os.environ.get('CODEX_HOME', _home('.codex')))
        return root / 'auth.json'

    def load(self) -> Optional[Token]:
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        if str(data.get('auth_mode', '')).lower() != 'chatgpt':
            return None
        tokens = data.get('tokens') or {}
        access = tokens.get('access_token') or ''
        if not access:
            return None
        return Token(
            access_token=access,
            refresh_token=tokens.get('refresh_token') or '',
            expires_at=_jwt_exp(access),
            account_id=tokens.get('account_id') or '',
            id_token=tokens.get('id_token') or '',
        )

    def save(self, token: Token) -> None:
        path = self.credentials_path()
        try:
            data = json.loads(path.read_text('utf-8')) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        tokens = data.get('tokens') or {}
        tokens.update({
            'access_token': token.access_token,
            'refresh_token': token.refresh_token,
            'account_id': token.account_id,
        })
        if token.id_token:
            tokens['id_token'] = token.id_token
        data['tokens'] = tokens
        data.setdefault('auth_mode', 'chatgpt')
        data['last_refresh'] = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        _atomic_write(path, data)

    def headers(self, token: Token) -> dict:
        headers = {
            'Authorization': f'Bearer {token.access_token}',
            'originator': 'codex_cli_rs',
            'User-Agent': USER_AGENT,
        }
        if token.account_id:
            headers['chatgpt-account-id'] = token.account_id
        return headers


class ClaudeSource(OAuthSource):
    """Session written by Claude Code (Anthropic OAuth)."""

    name = 'claude'
    label = 'Claude Code (Anthropic)'
    default_base_url = 'https://api.anthropic.com/v1'
    default_protocol = 'anthropic'
    token_url = 'https://console.anthropic.com/v1/oauth/token'
    client_id = '9d1c250a-e61b-44d9-88ed-5944d1962f5e'
    scope = 'user:inference user:profile'
    login_hint = 'Abra o Claude Code e faça login (`claude`), depois tente novamente.'

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_CLAUDE_CREDENTIALS')
        if override:
            return Path(override)
        return _home('.claude', '.credentials.json')

    def load(self) -> Optional[Token]:
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        oauth = data.get('claudeAiOauth') or data
        access = oauth.get('accessToken') or oauth.get('access_token') or ''
        if not access:
            return None
        expires_ms = float(oauth.get('expiresAt') or oauth.get('expires_at') or 0)
        expires_at = expires_ms / 1000.0 if expires_ms > 1e11 else expires_ms
        return Token(
            access_token=access,
            refresh_token=oauth.get('refreshToken') or oauth.get('refresh_token') or '',
            expires_at=expires_at or _jwt_exp(access),
            account_id=oauth.get('subscriptionType') or '',
        )

    def save(self, token: Token) -> None:
        path = self.credentials_path()
        try:
            data = json.loads(path.read_text('utf-8')) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        oauth = data.get('claudeAiOauth')
        if not isinstance(oauth, dict):
            oauth = {}
            data['claudeAiOauth'] = oauth
        oauth['accessToken'] = token.access_token
        if token.refresh_token:
            oauth['refreshToken'] = token.refresh_token
        if token.expires_at:
            oauth['expiresAt'] = int(token.expires_at * 1000)
        _atomic_write(path, data)

    def headers(self, token: Token) -> dict:
        return {
            'Authorization': f'Bearer {token.access_token}',
            'anthropic-version': '2023-06-01',
            'anthropic-beta': 'oauth-2025-04-20',
            'User-Agent': USER_AGENT,
        }


class GeminiSource(OAuthSource):
    """Session written by gemini-cli (Google OAuth)."""

    name = 'gemini'
    label = 'Gemini CLI (Google)'
    default_base_url = 'https://generativelanguage.googleapis.com/v1beta/openai'
    default_protocol = 'chat'
    token_url = 'https://oauth2.googleapis.com/token'
    client_id = ''          # configure em auth.client_id (ou env) — ver docs/OAUTH.md
    client_secret = ''
    scope = ('https://www.googleapis.com/auth/cloud-platform '
             'https://www.googleapis.com/auth/userinfo.email openid email profile')
    login_hint = 'Rode `gemini` e faça login, ou preencha auth.client_id/client_secret.'

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_GEMINI_CREDENTIALS')
        if override:
            return Path(override)
        return _home('.gemini', 'oauth_creds.json')

    def load(self) -> Optional[Token]:
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        access = data.get('access_token') or ''
        if not access:
            return None
        expiry_ms = float(data.get('expiry_date') or 0)
        expires_at = expiry_ms / 1000.0 if expiry_ms > 1e11 else expiry_ms
        return Token(
            access_token=access,
            refresh_token=data.get('refresh_token') or '',
            expires_at=expires_at or _jwt_exp(access),
        )

    def save(self, token: Token) -> None:
        path = self.credentials_path()
        try:
            data = json.loads(path.read_text('utf-8')) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        data['access_token'] = token.access_token
        if token.refresh_token:
            data['refresh_token'] = token.refresh_token
        if token.expires_at:
            data['expiry_date'] = int(token.expires_at * 1000)
        _atomic_write(path, data)

    def default_client_id(self) -> str:
        return os.environ.get('AI_BRIDGE_GEMINI_CLIENT_ID', '') or self.client_id

    def default_client_secret(self) -> str:
        return os.environ.get('AI_BRIDGE_GEMINI_CLIENT_SECRET', '') or self.client_secret


def _dig(data: dict, path: str, default=''):
    """Read ``a.b.c`` from nested dicts without raising."""
    cur = data
    for part in path.split('.'):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur if cur is not None else default


class GcloudSource(OAuthSource):
    """gcloud Application Default Credentials (``gcloud auth application-default login``).

    O arquivo ADC não guarda access token: ele é obtido no refresh usando o
    client_id/client_secret públicos gravados no próprio arquivo.
    """

    name = 'gcloud'
    label = 'gcloud ADC (Google)'
    default_base_url = ''
    default_protocol = 'chat'
    token_url = 'https://oauth2.googleapis.com/token'
    scope = ''  # Google recusa scope no refresh deste fluxo
    login_hint = 'Rode `gcloud auth application-default login` e tente novamente.'

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_GCLOUD_ADC')
        if override:
            return Path(override)
        appdata = os.environ.get('APPDATA')
        candidates = []
        if appdata:
            candidates.append(Path(appdata) / 'gcloud' / 'application_default_credentials.json')
        candidates.append(_home('.config', 'gcloud', 'application_default_credentials.json'))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

    def load(self) -> Optional[Token]:
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return None
        if str(data.get('type', '')) != 'authorized_user' or not data.get('refresh_token'):
            return None
        return Token(
            access_token='',
            refresh_token=str(data.get('refresh_token') or ''),
            expires_at=0.0,
            extra={'client_id': str(data.get('client_id') or ''),
                   'client_secret': str(data.get('client_secret') or '')},
        )

    def save(self, token: Token) -> None:
        # O ADC é somente-leitura para nós: o refresh_token continua no arquivo.
        return None

    def refresh(self, token: Token, *, client_id: str = '', client_secret: str = '',
                token_url: str = '') -> Optional[Token]:
        return super().refresh(
            token,
            client_id=client_id or str(token.extra.get('client_id') or ''),
            client_secret=client_secret or str(token.extra.get('client_secret') or ''),
            token_url=token_url,
        )


class HuggingFaceSource(OAuthSource):
    """Token gravado por ``huggingface-cli login`` (router OpenAI-compatible)."""

    name = 'huggingface'
    label = 'Hugging Face'
    default_base_url = 'https://router.huggingface.co/v1'
    default_protocol = 'chat'
    login_hint = 'Rode `huggingface-cli login` (ou `hf auth login`) e tente novamente.'

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_HF_TOKEN_FILE')
        if override:
            return Path(override)
        hf_home = os.environ.get('HF_HOME')
        if hf_home:
            return Path(hf_home) / 'token'
        return _home('.cache', 'huggingface', 'token')

    def load(self) -> Optional[Token]:
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            token = path.read_text('utf-8').strip()
        except OSError:
            return None
        if not token:
            return None
        return Token(access_token=token)


def _toml_flat_dump(data: dict) -> str:
    """Serialize a flat TOML table (all scalar values), used by the Wrangler config."""
    lines = []
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = 'true' if value else 'false'
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(str(value))
        lines.append(f'{key} = {rendered}')
    return '\n'.join(lines) + '\n'


class CloudflareSource(OAuthSource):
    """Sessão do ``wrangler login`` (Workers AI / AI Gateway).

    O arquivo é TOML e guarda ``oauth_token``/``refresh_token``/``expiration_time``.
    O endpoint de inferência exige o ``account_id`` na URL, então o provedor
    precisa informar ``base_url`` (ex.:
    ``https://api.cloudflare.com/client/v4/accounts/<id>/ai/v1``).
    """

    name = 'cloudflare'
    label = 'Cloudflare Wrangler (Workers AI)'
    default_base_url = ''
    default_protocol = 'chat'
    token_url = 'https://dash.cloudflare.com/oauth2/token'
    client_id = '54d11594-84e4-41aa-b438-e81b8fa78ee7'
    scope = ''
    login_hint = ('Rode `wrangler login` e informe a base_url '
                  'https://api.cloudflare.com/client/v4/accounts/<account_id>/ai/v1')

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_WRANGLER_CONFIG')
        if override:
            return Path(override)
        candidates = []
        appdata = os.environ.get('APPDATA')
        if appdata:
            candidates.append(Path(appdata) / '.wrangler' / 'config' / 'default.toml')
        candidates.append(_home('.wrangler', 'config', 'default.toml'))
        candidates.append(_home('.config', '.wrangler', 'config', 'default.toml'))
        for candidate in candidates:
            if candidate.is_file():
                return candidate
        return candidates[0]

    def _read(self) -> dict:
        path = self.credentials_path()
        if tomllib is None or not path.is_file():
            return {}
        try:
            return tomllib.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            return {}

    def load(self) -> Optional[Token]:
        data = self._read()
        access = str(data.get('oauth_token') or '')
        if not access:
            return None
        expires_at = 0.0
        raw_exp = data.get('expiration_time')
        if isinstance(raw_exp, str):
            try:
                expires_at = datetime.fromisoformat(raw_exp.replace('Z', '+00:00')).timestamp()
            except ValueError:
                expires_at = 0.0
        return Token(
            access_token=access,
            refresh_token=str(data.get('refresh_token') or ''),
            expires_at=expires_at or _jwt_exp(access),
        )

    def save(self, token: Token) -> None:
        data = self._read()
        data['oauth_token'] = token.access_token
        if token.refresh_token:
            data['refresh_token'] = token.refresh_token
        if token.expires_at:
            data['expiration_time'] = datetime.fromtimestamp(
                token.expires_at, timezone.utc).isoformat().replace('+00:00', 'Z')
        path = self.credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.ai-bridge.tmp')
        tmp.write_text(_toml_flat_dump(data), 'utf-8')
        tmp.replace(path)


class CopilotSource(OAuthSource):
    """GitHub Copilot token from the GitHub CLI session (``gh auth login``).

    O CLI do Copilot usa o mesmo OAuth do ``gh``. A API do Copilot exige
    cabeçalhos de editor; ajuste ``base_url``/``auth.headers`` se o seu plano
    usar outro endpoint.
    """

    name = 'copilot'
    label = 'GitHub Copilot CLI'
    default_base_url = 'https://api.githubcopilot.com'
    default_protocol = 'chat'
    login_hint = 'Rode `gh auth login` (com escopo copilot) e tente novamente.'

    def credentials_path(self) -> Path:
        override = os.environ.get('AI_BRIDGE_GH_HOSTS')
        if override:
            return Path(override)
        appdata = os.environ.get('APPDATA')
        if appdata:
            return Path(appdata) / 'GitHub CLI' / 'hosts.yml'
        return _home('.config', 'gh', 'hosts.yml')

    def load(self) -> Optional[Token]:
        env_token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        if env_token:
            return Token(access_token=env_token)
        path = self.credentials_path()
        if not path.is_file():
            return None
        try:
            text = path.read_text('utf-8', errors='replace')
        except OSError:
            return None
        import re
        match = re.search(r'oauth_token:\s*(\S+)', text)
        if not match:
            return None
        return Token(access_token=match.group(1))

    def save(self, token: Token) -> None:
        return None

    def headers(self, token: Token) -> dict:
        return {
            'Authorization': f'Bearer {token.access_token}',
            'Copilot-Integration-Id': 'vscode-chat',
            'Editor-Version': 'vscode/1.95.0',
        }


SOURCES = {source.name: source for source in (CodexSource(), ClaudeSource(), GeminiSource(),
                                             GcloudSource(), HuggingFaceSource(),
                                             CloudflareSource(), CopilotSource())}
_CACHE: dict[str, Token] = {}
_LOCK = threading.RLock()


# ─── PKCE (login próprio, quando não existe sessão da CLI) ─────────────────────

AUTHORIZE_URLS = {
    'codex': 'https://auth.openai.com/oauth/authorize',
    'claude': 'https://console.anthropic.com/oauth/authorize',
    'gemini': 'https://accounts.google.com/o/oauth2/v2/auth',
}

# Parâmetros extras que cada provedor espera no authorize.
AUTHORIZE_EXTRA = {
    'codex': {'id_token_add_organizations': 'true', 'codex_cli_simplified_flow': 'true'},
    'claude': {'code': 'true'},
    'gemini': {'access_type': 'offline', 'prompt': 'consent', 'include_granted_scopes': 'true'},
}


def new_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge) using S256."""
    import hashlib
    import secrets

    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode('ascii')).digest()
    challenge = base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')
    return verifier, challenge


def authorize_url(source: OAuthSource, redirect_uri: str, state: str,
                  *, client_id: str = '', challenge: str = '') -> str:
    """Build the browser URL for the bridge's own OAuth login."""
    from urllib.parse import urlencode

    name = source.name
    if name not in AUTHORIZE_URLS:
        raise ValueError(f'Login OAuth próprio não configurado para {name!r}.')
    cid = client_id or source.default_client_id()
    if not cid:
        raise ValueError(
            f'{name}: client_id não configurado. Preencha auth.client_id ou a variável de ambiente.'
        )
    params = {
        'response_type': 'code',
        'client_id': cid,
        'redirect_uri': redirect_uri,
        'scope': source.scope or 'openid profile email',
        'state': state,
    }
    if challenge:
        params['code_challenge'] = challenge
        params['code_challenge_method'] = 'S256'
    params.update(AUTHORIZE_EXTRA.get(name, {}))
    return AUTHORIZE_URLS[name] + '?' + urlencode(params)


def exchange_code(source: OAuthSource, *, code: str, verifier: str, redirect_uri: str,
                  client_id: str = '', client_secret: str = '', token_url: str = '') -> Token:
    """Trade the authorization code for tokens and persist them like the CLI does."""
    url = token_url or source.token_url
    cid = client_id or source.default_client_id()
    secret = client_secret or source.default_client_secret()
    if not url or not cid:
        raise ValueError(f'{source.name}: endpoint/client_id de token não configurado.')
    body = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
        'client_id': cid,
        'code_verifier': verifier,
    }
    if secret:
        body['client_secret'] = secret
    resp = httpx.post(url, json=body, timeout=httpx.Timeout(20.0, read=60.0),
                      headers={'Content-Type': 'application/json', 'User-Agent': USER_AGENT})
    if resp.status_code != 200:
        raise ValueError(f'{source.name}: troca de código recusada ({resp.status_code}): {resp.text[:200]}')
    payload = resp.json()
    access = payload.get('access_token') or ''
    if not access:
        raise ValueError(f'{source.name}: resposta sem access_token.')
    expires_in = float(payload.get('expires_in') or 0)
    token = Token(
        access_token=access,
        refresh_token=payload.get('refresh_token') or '',
        expires_at=time.time() + expires_in if expires_in else _jwt_exp(access),
        id_token=payload.get('id_token') or '',
    )
    if source.name == 'codex':
        account_id = _account_id_from_jwt(token.id_token) or _account_id_from_jwt(access)
        token.account_id = account_id
    source.save(token)
    return token


def _account_id_from_jwt(token: str) -> str:
    try:
        payload = token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload.encode('ascii')))
        auth = data.get('https://api.openai.com/auth') or {}
        return str(auth.get('chatgpt_account_id') or auth.get('account_id') or '')
    except Exception:
        return ''




def get_source(name: str) -> OAuthSource:
    try:
        return SOURCES[name]
    except KeyError:
        options = ', '.join(sorted(SOURCES))
        raise ValueError(f'Fonte OAuth desconhecida: {name!r} (opções: {options}).')


def is_oauth(provider: dict) -> bool:
    auth = provider.get('auth') or {}
    return str(auth.get('kind', '')).lower() == 'oauth'


def invalidate(provider_name: str) -> None:
    with _LOCK:
        _CACHE.pop(provider_name, None)


def _load_or_refresh(provider: dict, *, force: bool = False) -> Token:
    auth = provider.get('auth') or {}
    source = get_source(str(auth.get('source', '')))
    name = str(provider.get('name', ''))

    with _LOCK:
        token = None if force else _CACHE.get(name)

    if token is None:
        token = source.load()
        if token is None:
            raise MissingCredentials(name, source.name, source.login_hint)

    if not token.access_token or token.expired() or force:
        refreshed = source.refresh(
            token,
            client_id=str(auth.get('client_id', '') or ''),
            client_secret=str(auth.get('client_secret', '') or ''),
            token_url=str(auth.get('token_url', '') or ''),
        )
        if refreshed is None:
            raise MissingCredentials(name, source.name, source.login_hint)
        try:
            source.save(refreshed)
        except OSError as exc:  # token válido em memória mesmo sem escrever no disco
            log.warning('%s: não foi possível gravar o token renovado: %s', source.name, exc)
        token = refreshed

    with _LOCK:
        _CACHE[name] = token
    return token


def resolve(provider: dict, *, protocol: str = '', force_refresh: bool = False) -> ResolvedAuth:
    """Return headers/base_url/protocol for one provider (OAuth or API key)."""
    if not is_oauth(provider):
        key = str(provider.get('api_key') or '')
        if not key and provider.get('env_key'):
            key = os.environ.get(str(provider['env_key']), '')
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': USER_AGENT,
        }
        if key.strip():
            headers['Authorization'] = f'Bearer {key.strip()}'
        return ResolvedAuth(
            headers=headers,
            base_url=str(provider.get('base_url', '')).rstrip('/'),
            protocol=protocol or str(provider.get('protocol', '') or 'chat'),
        )

    auth = provider.get('auth') or {}
    source = get_source(str(auth.get('source', '')))
    token = _load_or_refresh(provider, force=force_refresh)
    headers = {
        'Content-Type': 'application/json',
        'User-Agent': USER_AGENT,
        **source.headers(token),
    }
    base_url = str(provider.get('base_url', '') or source.default_base_url).rstrip('/')
    if not base_url:
        raise ConfigurationError(
            str(provider.get('name', '')), source.name,
            f'Informe a base_url do provedor (fonte {source.name} não tem padrão).',
        )
    return ResolvedAuth(
        headers=headers,
        base_url=base_url,
        protocol=protocol or str(provider.get('protocol', '') or source.default_protocol),
        source=source.name,
        account_id=token.account_id,
    )


def status(provider: dict) -> dict:
    """Non-secret status for the UI (never returns the token)."""
    if not is_oauth(provider):
        has_key = bool(provider.get('api_key'))
        if not has_key and provider.get('env_key'):
            has_key = bool(os.environ.get(str(provider['env_key']), ''))
        return {'kind': 'api_key', 'has_key': has_key,
                'env_key': provider.get('env_key', '')}
    auth = provider.get('auth') or {}
    source_name = str(auth.get('source', ''))
    try:
        source = get_source(source_name)
    except ValueError as exc:
        return {'kind': 'oauth', 'source': source_name, 'connected': False, 'error': str(exc)}
    token = None
    try:
        with _LOCK:
            token = _CACHE.get(str(provider.get('name', '')))
        token = token or source.load()
    except OSError:
        token = None
    if token is None:
        return {'kind': 'oauth', 'source': source_name, 'connected': False,
                'hint': source.login_hint}
    return {
        'kind': 'oauth',
        'source': source_name,
        'connected': True,
        'expires_at': token.expires_at,
        'expired': token.expired(0),
        'account_id': token.account_id,
    }

