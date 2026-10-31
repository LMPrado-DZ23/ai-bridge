"""Política de roteamento entre provedores.

Regra de privacidade: **fallback é opt-in**. Por padrão o proxy tenta apenas o
provedor selecionado; tentar outro provedor sem consentimento explícito poderia
enviar contexto/código a um destino diferente.
"""
from __future__ import annotations

DEFAULT_POLICY = {
    'allow_fallback': False,
    'max_attempts': 1,
}


class RoutingError(ValueError):
    """Nenhum provedor disponível para a política pedida."""


def _priority(provider: dict) -> int:
    try:
        return int(provider.get('priority', 100))
    except (TypeError, ValueError):
        return 100


def resolve_order(providers, explicit=None):
    """Ordena provedores habilitados.

    `explicit` (lista de nomes) tem prioridade sobre o campo `priority`;
    provedores com `enabled == False` nunca entram.
    """
    active = [p for p in providers if p.get('enabled', True) is not False]
    if not active:
        raise RoutingError('nenhum provedor habilitado')

    explicit = [str(name) for name in (explicit or [])]
    by_name = {p['name']: p for p in active}
    ordered = []
    for name in explicit:
        provider = by_name.get(name)
        if provider is not None and provider not in ordered:
            ordered.append(provider)
    rest = sorted((p for p in active if p not in ordered), key=lambda p: (_priority(p), p['name']))
    return ordered + rest


def attempts_allowed(policy=None, candidates=1):
    """Quantas tentativas a política permite, sem nunca passar dos candidatos."""
    merged = dict(DEFAULT_POLICY)
    merged.update(policy or {})
    if not merged['allow_fallback']:
        return min(1, max(0, candidates))
    limit = max(1, int(merged.get('max_attempts', 1)))
    return min(limit, max(0, candidates))


def fallback_candidates(order, tried):
    """Próximos candidatos ainda não tentados, na ordem resolvida."""
    tried = set(tried)
    return [provider for provider in order if provider['name'] not in tried]
