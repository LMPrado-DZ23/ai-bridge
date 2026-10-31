"""Descoberta automática de modelos de qualquer provedor.

Busca ``GET {base_url}/models`` (OpenAI-compatible e Anthropic), com fallback
para o endpoint nativo do Ollama (``/api/tags``), e marca quais modelos são
gratuitos quando o provedor sinaliza isso no id (``:free``, prefixo ``free-``)
ou quando o endpoint é local.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

FREE_MARKERS = (':free', '-free', 'free-', '/free')


def is_local(base_url: str) -> bool:
    host = (urlsplit(base_url).hostname or '').lower()
    return host in ('localhost', '127.0.0.1', '0.0.0.0', '::1')


def classify_free(provider_name: str, model_id: str, base_url: str) -> bool:
    if is_local(base_url):
        return True
    lowered = model_id.lower()
    return any(marker in lowered for marker in FREE_MARKERS)


def _parse_models(payload) -> list[dict]:
    """Accept OpenAI (data[]), Anthropic (data[] with display_name) and Ollama."""
    items = []
    if isinstance(payload, dict):
        if isinstance(payload.get('data'), list):
            items = payload['data']
        elif isinstance(payload.get('models'), list):
            items = payload['models']
    elif isinstance(payload, list):
        items = payload
    models = []
    for item in items:
        if isinstance(item, str):
            models.append({'id': item, 'label': item})
            continue
        if not isinstance(item, dict):
            continue
        model_id = item.get('id') or item.get('name') or item.get('model')
        if not model_id:
            continue
        label = item.get('display_name') or item.get('displayName') or item.get('name') or model_id
        models.append({'id': str(model_id), 'label': str(label)})
    return models


def fetch_models(base_url: str, headers: dict, provider_name: str = '',
                 timeout: float = 20.0) -> dict:
    """Return ``{ok, models:[{id,label,free}], total, free_count}`` or an error."""
    base = (base_url or '').rstrip('/')
    if not base:
        return {'ok': False, 'error': 'Informe a URL base do provedor.'}

    attempts = [(base + '/models', headers)]
    # Ollama expõe /api/tags no servidor nativo, além de /v1/models.
    if is_local(base) and base.endswith('/v1'):
        attempts.append((base[: -len('/v1')] + '/api/tags', headers))

    last_error = ''
    for url, request_headers in attempts:
        try:
            resp = httpx.get(url, headers=request_headers, timeout=timeout)
        except httpx.HTTPError as exc:
            last_error = str(exc)
            continue
        if resp.status_code != 200:
            last_error = f'HTTP {resp.status_code}: {resp.text[:200]}'
            continue
        try:
            payload = resp.json()
        except ValueError:
            last_error = 'resposta não é JSON'
            continue
        models = _parse_models(payload)
        if not models:
            last_error = 'nenhum modelo retornado'
            continue
        for model in models:
            model['free'] = classify_free(provider_name, model['id'], base_url)
        models.sort(key=lambda m: m['id'].lower())
        return {
            'ok': True,
            'models': models,
            'total': len(models),
            'free_count': sum(1 for model in models if model['free']),
        }
    return {'ok': False, 'error': last_error or 'falha ao buscar modelos'}
