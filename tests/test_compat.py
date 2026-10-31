"""Matriz de compatibilidade: nada é anunciado sem verificação."""
import pytest

from ai_bridge import compat


def test_matrix_shape_and_vocabulary():
    for name, entry in compat.MATRIX.items():
        for capability in compat.CAPABILITIES:
            assert isinstance(entry.get(capability), bool), f'{name}/{capability}'
        assert set(entry['verified']) <= set(compat.CAPABILITIES), name
        assert entry['notes'], name


def test_verified_is_subset_of_declared():
    for name, entry in compat.MATRIX.items():
        for capability in entry['verified']:
            assert entry[capability] is True, f'{name} verifica {capability} que não declara'


def test_supports_only_verified_capabilities():
    assert compat.supports('DeepSeek', 'responses') is True
    assert compat.supports('DeepSeek', 'images') is False
    assert compat.supports('OpenAI', 'tools') is True
    assert compat.supports('Groq', 'responses') is False
    assert compat.supports('NaoExiste', 'chat') is False


def test_unknown_provider_is_marked_unknown():
    data = compat.capabilities('NaoExiste')
    assert data['known'] is False
    assert all(value is None for value in data['capabilities'].values())


def test_invalid_capability_raises():
    with pytest.raises(ValueError):
        compat.supports('DeepSeek', 'telepatia')
