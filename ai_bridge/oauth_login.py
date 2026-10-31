"""Bridge-owned OAuth login (PKCE) used when the CLI has no session.

Flow:
1. ``begin(provider)`` builds the authorize URL, remembers verifier/state and,
   when possible, starts the local callback server on the redirect URI that the
   provider client registered (Codex: http://localhost:1455/auth/callback).
2. The UI opens that URL in the browser.
3. The provider redirects to the local callback with ``code``; the handler calls
   ``complete()``, which exchanges the code and stores the session in the same
   file the CLI uses.
4. The page tells the user to return to the app.

State lives in memory only (single-user desktop app); nothing secret is logged.
"""
from __future__ import annotations

import html
import http.server
import logging
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Optional

from . import oauth

log = logging.getLogger(__name__)

PENDING_TTL_SECONDS = 900
_PENDING: dict[str, 'PendingLogin'] = {}
_SERVERS: dict[str, http.server.HTTPServer] = {}


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


def _page(message: str, ok: bool) -> str:
    color = '#34d399' if ok else '#f87171'
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<title>AI Bridge — login</title></head>'
        '<body style="font-family:system-ui;background:#0b0f19;color:#e5e7eb;'
        'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">'
        f'<div style="text-align:center;max-width:34rem;padding:24px">'
        f'<h2 style="color:{color};margin:0 0 8px">AI Bridge</h2>'
        f'<p style="color:#cbd5e1">{html.escape(message)}</p>'
        '<p style="color:#64748b;font-size:13px">Pode fechar esta aba e voltar ao AI Bridge.</p>'
        '</div></body></html>'
    )


def _make_handler(callback_path: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - stdlib naming
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != callback_path:
                self.send_response(404)
                self.end_headers()
                return
            query = urllib.parse.parse_qs(parsed.query)
            state = (query.get('state') or [''])[0]
            code = (query.get('code') or [''])[0]
            error = (query.get('error') or [''])[0]
            try:
                if error:
                    raise ValueError(f'login cancelado: {error}')
                if not code:
                    raise ValueError('código de autorização ausente')
                complete(state, code)
                body, status = _page('Login concluído com sucesso.', True), 200
            except Exception as exc:  # noqa: BLE001 - shown to the user in the browser
                log.warning('oauth callback failed: %s', exc)
                body, status = _page(f'Falha no login: {exc}', False), 400
            payload = body.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            server = _SERVERS.pop(state, None)
            if server is not None:
                threading.Thread(target=server.shutdown, daemon=True).start()

        def log_message(self, *args):  # silence per-request logging
            return

    return Handler


def _start_callback_server(redirect_uri: str, state: str) -> Optional[http.server.HTTPServer]:
    parsed = urllib.parse.urlsplit(redirect_uri)
    host = parsed.hostname or '127.0.0.1'
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    path = parsed.path or '/'
    handler = _make_handler(path)
    try:
        server = http.server.HTTPServer((host, port), handler)
    except OSError as exc:
        raise ValueError(
            f'Não consegui abrir {host}:{port} para receber o login ({exc}). '
            'Feche um login em andamento (codex login) e tente de novo.'
        ) from exc
    threading.Thread(target=server.serve_forever, daemon=True, name='ab-oauth-callback').start()
    _SERVERS[state] = server
    return server


def begin(provider: dict, redirect_uri: str = '') -> dict:
    """Create a pending login, start the callback server and return the URL."""
    auth = provider.get('auth') or {}
    source = oauth.get_source(str(auth.get('source', '')))
    verifier, challenge = oauth.new_pkce_pair()
    state = secrets.token_urlsafe(24)

    redirect = (redirect_uri or str(auth.get('redirect_uri') or '')
                or getattr(source, 'callback_url', '') or '')
    if not redirect:
        redirect = 'http://127.0.0.1:0/oauth/callback'  # substituído abaixo

    if ':0/' in redirect:
        # Porta livre escolhida pelo SO, depois de subir o servidor.
        parsed = urllib.parse.urlsplit(redirect)
        temp = http.server.HTTPServer((parsed.hostname or '127.0.0.1', 0), _make_handler(parsed.path or '/'))
        port = temp.server_address[1]
        redirect = f'http://{parsed.hostname or "127.0.0.1"}:{port}{parsed.path or "/"}'
        _prune()
        _PENDING[state] = PendingLogin(
            provider_name=str(provider.get('name', '')), source=source.name,
            verifier=verifier, redirect_uri=redirect, created_at=time.time(),
        )
        _SERVERS[state] = temp
        threading.Thread(target=temp.serve_forever, daemon=True, name='ab-oauth-callback').start()
    else:
        _prune()
        _PENDING[state] = PendingLogin(
            provider_name=str(provider.get('name', '')), source=source.name,
            verifier=verifier, redirect_uri=redirect, created_at=time.time(),
        )
        _start_callback_server(redirect, state)

    # Encerra o servidor se o usuário abandonar o login.
    def _expire():
        time.sleep(PENDING_TTL_SECONDS)
        if state in _PENDING:
            cancel(state)
    threading.Thread(target=_expire, daemon=True, name='ab-oauth-expire').start()

    url = oauth.authorize_url(
        source, redirect, state,
        client_id=str(auth.get('client_id', '') or ''),
        challenge=challenge,
    )
    return {'url': url, 'state': state, 'source': source.name, 'redirect_uri': redirect}


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
    states = [state] if state else list(_PENDING)
    for key in states:
        _PENDING.pop(key, None)
        server = _SERVERS.pop(key, None)
        if server is not None:
            server.shutdown()
