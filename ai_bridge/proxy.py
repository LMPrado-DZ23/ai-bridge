"""
Local HTTP proxy that implements the Anthropic Messages API and routes to
OpenAI-compatible providers based on the model prefix.
"""
import json
import socket
import threading
import logging

from flask import Flask, request, Response, jsonify
import httpx

from . import config as cfg
from . import oauth
from . import translate

app = Flask(__name__)
log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_port: int | None = None


# ─── Upstream helpers ──────────────────────────────────────────────────────────

def _auth_error(exc: oauth.MissingCredentials):
    return jsonify({
        'type': 'error',
        'error': {'type': 'authentication_error', 'message': str(exc)},
        'error_msg': str(exc),
    }), 401


def _resolve(provider: dict, *, force_refresh: bool = False) -> oauth.ResolvedAuth:
    return oauth.resolve(provider, force_refresh=force_refresh)


def _post_json(provider: dict, auth: oauth.ResolvedAuth, url: str, payload: dict,
               timeout: httpx.Timeout | None = None):
    """POST JSON to upstream; on 401 refresh the OAuth token once and retry."""
    timeout = timeout or httpx.Timeout(30.0, read=300.0)
    resp = httpx.post(url, json=payload, headers=auth.headers, timeout=timeout)
    if resp.status_code == 401 and oauth.is_oauth(provider):
        try:
            retried = _resolve(provider, force_refresh=True)
        except oauth.MissingCredentials:
            return resp
        resp = httpx.post(url, json=payload, headers=retried.headers, timeout=timeout)
    return resp


def _upstream_stream(url: str, payload: dict, auth: oauth.ResolvedAuth, error_event: str):
    """Pass SSE chunks through unchanged (Anthropic or Responses wire format)."""
    def generate():
        try:
            with httpx.stream('POST', url, json=payload, headers=auth.headers,
                              timeout=httpx.Timeout(30.0, read=600.0)) as r:
                if r.status_code != 200:
                    body = r.read().decode('utf-8', errors='replace')
                    err = json.dumps({'type': 'error',
                                      'error': {'type': 'api_error', 'message': body[:800]}})
                    yield f'event: {error_event}\ndata: {err}\n\n'
                    return
                for chunk in r.iter_bytes():
                    if chunk:
                        yield chunk
        except httpx.TimeoutException:
            err = json.dumps({'type': 'error',
                              'error': {'type': 'overloaded_error', 'message': 'Request timed out'}})
            yield f'event: {error_event}\ndata: {err}\n\n'
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an SSE error
            err = json.dumps({'type': 'error',
                              'error': {'type': 'api_error', 'message': str(exc)}})
            yield f'event: {error_event}\ndata: {err}\n\n'

    return Response(
        generate(),
        content_type='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                 'Connection': 'keep-alive'},
    )


def _passthrough(auth: oauth.ResolvedAuth, url: str, payload: dict, stream: bool,
                 *, error_event: str = 'error', provider: dict | None = None):
    """Forward a request to an upstream that speaks the same protocol."""
    if stream:
        return _upstream_stream(url, payload, auth, error_event)
    if provider is not None:
        resp = _post_json(provider, auth, url, payload,
                          timeout=httpx.Timeout(30.0, read=600.0))
    else:
        resp = httpx.post(url, json=payload, headers=auth.headers,
                          timeout=httpx.Timeout(30.0, read=600.0))
    if resp.status_code != 200:
        return jsonify({'type': 'error',
                        'error': {'type': 'api_error', 'message': resp.text[:800]}}), resp.status_code
    return jsonify(resp.json())



# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'port': _port})


def _oauth_page(message: str, ok: bool) -> str:
    import html

    safe = html.escape(message)
    color = '#16a34a' if ok else '#dc2626'
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<title>AI Bridge — login</title></head>'
        '<body style="font-family:system-ui;background:#0b0f19;color:#e5e7eb;'
        'display:flex;align-items:center;justify-content:center;height:100vh;margin:0">'
        f'<div style="text-align:center;max-width:32rem"><h2 style="color:{color}">AI Bridge</h2>'
        f'<p>{safe}</p></div></body></html>'
    )


@app.route('/oauth/callback')
def oauth_callback():
    """Loopback redirect for the bridge's own PKCE login."""
    from . import oauth_login

    error = request.args.get('error', '')
    if error:
        return _oauth_page(f'Login cancelado: {error}', ok=False), 400
    try:
        oauth_login.complete(request.args.get('state', ''), request.args.get('code', ''))
    except Exception as exc:  # noqa: BLE001 - shown to the user in the browser
        log.warning('oauth callback failed: %s', exc)
        return _oauth_page(f'Falha no login: {exc}', ok=False), 400
    return _oauth_page('Login concluído. Pode fechar esta aba e voltar ao AI Bridge.', ok=True)



@app.route('/v1/messages', methods=['POST'])
def messages():
    data = request.get_json(force=True, silent=True) or {}
    model = data.get('model', '')

    provider = cfg.get_provider_for_model(model)
    if provider is None:
        return jsonify({
            'type': 'error',
            'error': {'type': 'not_found_error', 'message': f'Model not found in AI Bridge: {model}'},
        }), 404

    try:
        auth = _resolve(provider)
    except oauth.MissingCredentials as exc:
        return _auth_error(exc)

    actual_model = cfg.get_model_id(model) or (model.split('/', 1)[1] if '/' in model else model)
    stream = data.get('stream', False)

    # Provider speaks Anthropic natively (ex.: Claude Code OAuth): pass through.
    if auth.protocol == 'anthropic':
        url = auth.base_url.rstrip('/') + '/messages'
        return _passthrough(auth, url, {**data, 'model': actual_model}, stream, provider=provider)

    oai_req = translate.to_openai_request(data, actual_model)
    headers = auth.headers
    url = auth.base_url.rstrip('/') + '/chat/completions'


    try:
        if stream:
            def generate():
                try:
                    with httpx.stream(
                        'POST', url,
                        json=oai_req,
                        headers=headers,
                        timeout=httpx.Timeout(30.0, read=300.0),
                    ) as r:
                        if r.status_code != 200:
                            body = r.read()
                            err = json.dumps({
                                'type': 'error',
                                'error': {'type': 'api_error', 'message': body.decode('utf-8', errors='replace')},
                            })
                            yield f"event: error\ndata: {err}\n\n"
                            return
                        yield from translate.stream_to_anthropic(r.iter_lines(), model)
                except httpx.TimeoutException:
                    err = json.dumps({'type': 'error', 'error': {'type': 'overloaded_error', 'message': 'Request timed out'}})
                    yield f"event: error\ndata: {err}\n\n"
                except httpx.ConnectError as e:
                    err = json.dumps({'type': 'error', 'error': {'type': 'api_error', 'message': str(e)}})
                    yield f"event: error\ndata: {err}\n\n"

            return Response(
                generate(),
                content_type='text/event-stream',
                headers={
                    'Cache-Control': 'no-cache',
                    'X-Accel-Buffering': 'no',
                    'Connection': 'keep-alive',
                },
            )

        else:
            resp = _post_json(provider, auth, url, oai_req)
            if resp.status_code != 200:
                return jsonify({
                    'type': 'error',
                    'error': {'type': 'api_error', 'message': resp.text[:500]},
                }), resp.status_code
            return jsonify(translate.to_anthropic_response(resp.json(), model))

    except httpx.TimeoutException:
        return jsonify({
            'type': 'error',
            'error': {'type': 'overloaded_error', 'message': 'Request timed out'},
        }), 529
    except httpx.ConnectError as e:
        return jsonify({
            'type': 'error',
            'error': {'type': 'api_error', 'message': f'Connection failed: {e}'},
        }), 502
    except Exception as e:
        log.exception('Unexpected proxy error')
        return jsonify({
            'type': 'error',
            'error': {'type': 'api_error', 'message': str(e)},
        }), 500


@app.route('/v1/models')
def models():
    """List all configured models in OpenAI format."""
    data = []
    for p in cfg.get_providers():
        for m in p.get('models', []):
            label = m.get('label', m['id'])
            data.append({
                'id': f"{p['name']}/{m['id']}",
                'object': 'model',
                'created': 0,
                'owned_by': p['name'],
                'display_name': f"{label} · {p['name']}",
            })
    return jsonify({'object': 'list', 'data': data})


@app.route('/v1/codex-models')
def codex_models():
    """Return non-secret Codex model metadata for the loopback-only model picker.

    Codex may fetch model_catalog_url without forwarding provider authorization.
    The route exposes only configured model IDs/labels, never provider credentials.
    """
    catalog = []
    for provider in cfg.get_providers():
        for model in provider.get('models', []):
            model_id = f"{provider['name']}/{model['id']}"
            label = model.get('label', model['id'])
            catalog.append({
                'slug': model_id,
                # Match Codex Desktop's local model_catalog_json schema.
                'displayName': f"{label} · {provider['name']}",
                'display_name': f"{label} · {provider['name']}",
                'provider': 'ai_bridge',
                'hidden': False,
                'description': f"{label} via AI Bridge ({provider['name']}).",
                'default_reasoning_level': 'medium',
                'supported_reasoning_levels': [
                    {'effort': 'low', 'description': 'Respostas mais rápidas.'},
                    {'effort': 'medium', 'description': 'Equilíbrio entre velocidade e profundidade.'},
                    {'effort': 'high', 'description': 'Maior profundidade para tarefas complexas.'},
                ],
                'shell_type': 'shell_command',
                'visibility': 'list',
                'supported_in_api': True,
                'priority': len(catalog) + 1,
                'additional_speed_tiers': [],
                'service_tiers': [],
                'default_service_tier': None,
                'availability_nux': None,
                'upgrade': None,
                'support_verbosity': False,
                'default_verbosity': None,
                'apply_patch_tool_type': 'freeform',
                'web_search_tool_type': 'text',
                'truncation_policy': {'mode': 'tokens', 'limit': 10000},
                'effective_context_window_percent': 95,
                'experimental_supported_tools': [],
                'input_modalities': ['text'],
                'base_instructions': 'Modelo externo conectado pelo AI Bridge. Siga as instruções do usuário.',
            })
    return jsonify({'models': catalog})


@app.route('/v1/responses', methods=['POST'])
def responses():
    """Responses API adapter used by Codex; upstream remains OpenAI Chat Completions."""
    from . import responses_api
    data = request.get_json(force=True, silent=True) or {}
    model = str(data.get('model', ''))
    provider = cfg.get_provider_for_model(model)
    if provider is None:
        return jsonify({
            'error': {'message': f'Model not found in AI Bridge: {model}', 'type': 'invalid_request_error'}
        }), 404
    actual_model = cfg.get_model_id(model) or model

    try:
        auth = _resolve(provider)
    except oauth.MissingCredentials as exc:
        return _auth_error(exc)

    # Provider speaks the Responses API natively (Codex/ChatGPT OAuth, DeepSeek):
    # forward the request untouched so tools, reasoning items and streaming match.
    if auth.protocol == 'responses':
        url = auth.base_url.rstrip('/') + '/responses'
        payload = {**data, 'model': actual_model}
        # O backend do ChatGPT (Codex OAuth) recusa a requisição sem "store": false
        # explícito; outros provedores Responses decidem por conta própria.
        if (auth.source == 'codex' or 'chatgpt.com' in auth.base_url) and 'store' not in payload:
            payload['store'] = False
        return _passthrough(auth, url, payload,
                            bool(data.get('stream')), provider=provider)

    try:
        chat_request = responses_api.to_chat_request(data, actual_model)
    except ValueError as exc:
        return jsonify({'error': {'message': str(exc), 'type': 'invalid_request_error'}}), 400

    headers = auth.headers
    url = auth.base_url.rstrip('/') + '/chat/completions'
    try:
        # The adapter returns a valid Responses event sequence for streaming clients.
        # Upstream inference completes first because the current translator is non-streaming.
        resp = _post_json(provider, auth, url, chat_request)
        if resp.status_code != 200:
            return jsonify({
                'error': {'message': resp.text[:500], 'type': 'upstream_error'}
            }), resp.status_code
        response_data = responses_api.from_chat_response(resp.json(), model)
        if data.get('stream'):
            return Response(
                responses_api.as_sse(response_data),
                content_type='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
            )
        return jsonify(response_data)
    except httpx.TimeoutException:
        return jsonify({'error': {'message': 'Request timed out', 'type': 'server_error'}}), 529
    except httpx.ConnectError:
        return jsonify({'error': {'message': 'Connection failed to provider', 'type': 'server_error'}}), 502
    except Exception as exc:
        log.exception('Unexpected error (Responses API)')
        return jsonify({'error': {'message': str(exc), 'type': 'server_error'}}), 500


@app.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """OpenAI-compatible endpoint — for Codex, Cursor and other OpenAI clients."""
    data = request.get_json(force=True, silent=True) or {}
    model = data.get('model', '')

    provider = cfg.get_provider_for_model(model)
    if provider is None:
        return jsonify({
            'error': {
                'message': f'Model not found in AI Bridge: {model}',
                'type': 'invalid_request_error',
                'code': 'model_not_found',
            }
        }), 404

    actual_model = cfg.get_model_id(model) or (model.split('/', 1)[1] if '/' in model else model)
    req = {**data, 'model': actual_model}

    try:
        auth = _resolve(provider)
    except oauth.MissingCredentials as exc:
        return _auth_error(exc)

    if auth.protocol == 'responses':
        return jsonify({'error': {
            'message': 'Este provedor fala Responses API; use /v1/responses.',
            'type': 'invalid_request_error',
        }}), 501

    headers = auth.headers
    url = auth.base_url.rstrip('/') + '/chat/completions'
    stream = data.get('stream', False)


    try:
        if stream:
            def gen_oai():
                try:
                    with httpx.stream(
                        'POST', url, json=req, headers=headers,
                        timeout=httpx.Timeout(30.0, read=300.0),
                    ) as r:
                        if r.status_code != 200:
                            body = r.read()
                            yield f"data: {json.dumps({'error': {'message': body.decode('utf-8', errors='replace')}})}\n\n"
                            yield 'data: [DONE]\n\n'
                            return
                        for line in r.iter_lines():
                            if line:
                                yield line + '\n\n'
                except Exception as exc:
                    yield f"data: {json.dumps({'error': {'message': str(exc)}})}\n\n"
                    yield 'data: [DONE]\n\n'

            return Response(
                gen_oai(),
                content_type='text/event-stream',
                headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
            )

        resp = _post_json(provider, auth, url, req)
        if resp.status_code != 200:
            return jsonify({'error': {'message': resp.text[:500]}}), resp.status_code
        return jsonify(resp.json())

    except httpx.TimeoutException:
        return jsonify({'error': {'message': 'Request timed out', 'type': 'server_error'}}), 529
    except httpx.ConnectError as e:
        return jsonify({'error': {'message': f'Connection failed: {e}', 'type': 'server_error'}}), 502
    except Exception as e:
        log.exception('Unexpected proxy error (chat/completions)')
        return jsonify({'error': {'message': str(e), 'type': 'server_error'}}), 500


# ─── Server lifecycle ───────────────────────────────────────────────────────────

def _find_port(preferred: int) -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', preferred))
        s.close()
        return preferred
    except OSError:
        s.close()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start() -> int:
    global _thread, _port
    if _thread and _thread.is_alive():
        return _port  # type: ignore[return-value]

    preferred = cfg.get_port()
    _port = _find_port(preferred)

    def run():
        wz_log = logging.getLogger('werkzeug')
        wz_log.setLevel(logging.ERROR)
        app.run(host='127.0.0.1', port=_port, threaded=True, use_reloader=False)

    _thread = threading.Thread(target=run, daemon=True, name='ai-bridge-proxy')
    _thread.start()
    return _port  # type: ignore[return-value]


def get_port() -> int | None:
    return _port


def is_running() -> bool:
    return _thread is not None and _thread.is_alive()
