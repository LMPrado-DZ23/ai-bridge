"""Bridge-owned OAuth login (PKCE) used when the CLI has no session.

Flow:
1. ``begin(provider)`` builds the authorize URL and remembers verifier/state.
2. The UI opens that URL in the browser.
3. The provider redirects to the bridge's loopback callback with ``code``.
4. ``complete(state, code)`` exchanges the code, saves the session in the same
   place the CLI uses and returns the token.

State lives in memory only (single-user desktop app); nothing secret is logged.
"""
from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from . import oauth

log = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 600
_PENDING: dict[str, 'PendingLogin'] = {}


@dataclass
class PendingLogin:
    provider_name: str
    source: str
    verifier: str
    redirect_uri: str
    created_at: float


def _prune():
    now = time.time()
    for state, pending in list(_PENDING.items()):
        if now - pending.created_at > PENDING_TTL_SECONDS:
            _PENDING.pop(state, None)


def begin(provider: dict, redirect_uri: str) -> dict:
    """Create a pending login and return the browser URL."""
    auth = provider.get('auth') or {}
    source = oauth.get_source(str(auth.get('source', '')))
    verifier, challenge = oauth.new_pkce_pair()
    state = secrets.token_urlsafe(24)
    _prune()
    _PENDING[state] = PendingLogin(
        provider_name=str(provider.get('name', '')),
        source=source.name,
        verifier=verifier,
        redirect_uri=redirect_uri,
        created_at=time.time(),
    )
    url = oauth.authorize_url(
        source, redirect_uri, state,
        client_id=str(auth.get('client_id', '') or ''),
        challenge=challenge,
    )
    return {'url': url, 'state': state, 'source': source.name}


def complete(state: str, code: str) -> oauth.Token:
    pending = _PENDING.pop(state, None)
    if pending is None:
        raise ValueError('Login expirado ou desconhecido. Comece o login novamente.')
    source = oauth.get_source(pending.source)
    auth = {}
    provider = None
    from . import config as cfg  # local import to avoid cycles

    for candidate in cfg.get_providers():
        if candidate['name'] == pending.provider_name:
            provider = candidate
            auth = candidate.get('auth') or {}
            break
    token = oauth.exchange_code(
        source,
        code=code,
        verifier=pending.verifier,
        redirect_uri=pending.redirect_uri,
        client_id=str(auth.get('client_id', '') or ''),
        client_secret=str(auth.get('client_secret', '') or ''),
        token_url=str(auth.get('token_url', '') or ''),
    )
    oauth.invalidate(pending.provider_name)
    return token


def cancel(state: str = '') -> None:
    if state:
        _PENDING.pop(state, None)
    else:
        _PENDING.clear()
