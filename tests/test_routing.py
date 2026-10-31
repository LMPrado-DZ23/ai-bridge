"""Roteamento: ordem por prioridade e fallback somente opt-in."""
import pytest

from ai_bridge import routing


def _providers():
    return [
        {'name': 'Ollama', 'priority': 1},
        {'name': 'DeepSeek', 'priority': 2},
        {'name': 'OpenRouter', 'priority': 3},
    ]


def test_resolve_order_uses_priority():
    order = routing.resolve_order(_providers())
    assert [p['name'] for p in order] == ['Ollama', 'DeepSeek', 'OpenRouter']


def test_explicit_order_wins_over_priority():
    order = routing.resolve_order(_providers(), explicit=['OpenRouter', 'Ollama'])
    assert [p['name'] for p in order] == ['OpenRouter', 'Ollama', 'DeepSeek']


def test_disabled_providers_are_skipped():
    providers = _providers()
    providers[0]['enabled'] = False
    order = routing.resolve_order(providers)
    assert [p['name'] for p in order] == ['DeepSeek', 'OpenRouter']


def test_unknown_explicit_names_are_ignored_and_deduped():
    order = routing.resolve_order(_providers(), explicit=['DeepSeek', 'NaoExiste', 'DeepSeek'])
    assert [p['name'] for p in order] == ['DeepSeek', 'Ollama', 'OpenRouter']


def test_empty_provider_list_raises():
    with pytest.raises(routing.RoutingError):
        routing.resolve_order([])


def test_fallback_is_off_by_default():
    assert routing.attempts_allowed(None, candidates=3) == 1
    assert routing.DEFAULT_POLICY['allow_fallback'] is False


def test_fallback_opt_in_respects_limit_and_candidates():
    policy = {'allow_fallback': True, 'max_attempts': 2}
    assert routing.attempts_allowed(policy, candidates=3) == 2
    assert routing.attempts_allowed(policy, candidates=1) == 1
    assert routing.attempts_allowed({'allow_fallback': True, 'max_attempts': 99}, candidates=3) == 3


def test_fallback_candidates_exclude_tried():
    order = routing.resolve_order(_providers())
    remaining = routing.fallback_candidates(order, tried=['Ollama'])
    assert [p['name'] for p in remaining] == ['DeepSeek', 'OpenRouter']
