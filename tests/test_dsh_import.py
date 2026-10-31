"""Importação de provedores do perfil do DeepSeek Harness (fixtures, sem rede)."""
import json

import pytest

from ai_bridge import bridge as bridge_mod
from ai_bridge import config, dsh_import


PATCH = '''
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      ollama:
        displayName: Ollama (local)
        api: openai-completions
        apiKeyEnv: OLLAMA_API_KEY
        baseURL: http://127.0.0.1:11434/v1
        models:
          - {id: qwen3:8b, name: Qwen3 8B, contextWindow: 40960}
          - {id: qwen3.5:4b, name: Qwen3.5 4B}
      mimo:
        displayName: Xiaomi MiMo
        apiKeyEnv: MIMO_API_KEY
        baseURL: https://token-plan-sgp.xiaomimimo.com/v1
        models:
          - {id: mimo-v2.6-pro, name: MiMo v2.6 Pro}
      meta:
        apiKeyEnv: META_API_KEY
'''


@pytest.fixture
def dsh_home(tmp_path, monkeypatch):
    root = tmp_path / '.dsh'
    profile = root / 'profiles' / 'desktop'
    profile.mkdir(parents=True)
    (profile / 'cordis.patch.yml').write_text(PATCH, 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_DSH_HOME', str(root))
    return root


def test_reads_providers_with_base_url(dsh_home):
    providers = dsh_import.read_providers()
    names = [p['name'] for p in providers]
    assert names == ['mimo', 'ollama']  # "meta" não tem baseURL
    ollama = next(p for p in providers if p['name'] == 'ollama')
    assert ollama['base_url'] == 'http://127.0.0.1:11434/v1'
    assert ollama['env_key'] == 'OLLAMA_API_KEY'
    assert [m['id'] for m in ollama['models']] == ['qwen3:8b', 'qwen3.5:4b']
    assert ollama['models'][0]['label'] == 'Qwen3 8B'


def test_env_available(monkeypatch):
    assert dsh_import.env_available('') is True
    monkeypatch.delenv('AI_BRIDGE_MISSING_KEY', raising=False)
    assert dsh_import.env_available('AI_BRIDGE_MISSING_KEY') is False
    monkeypatch.setenv('AI_BRIDGE_PRESENT_KEY', 'x')
    assert dsh_import.env_available('AI_BRIDGE_PRESENT_KEY') is True


@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.setattr(bridge_mod.Bridge, '_sync_connected_targets', lambda self: None)
    return bridge_mod.Bridge()


def test_import_adds_providers_with_env_key(bridge, dsh_home, monkeypatch):
    captured = []
    monkeypatch.setattr(config, 'get_providers', lambda: [])
    monkeypatch.setattr(config, 'add_provider',
                        lambda *args, **kwargs: captured.append((args, kwargs)))

    res = bridge.import_dsh_providers()

    assert res['ok'] is True
    assert sorted(res['imported']) == ['mimo', 'ollama']
    assert res['skipped'] == []
    by_name = {args[0]: (args, kwargs) for args, kwargs in captured}
    args, kwargs = by_name['ollama']
    assert args[1] == 'http://127.0.0.1:11434/v1'
    assert args[2] == ''  # sem chave no keyring
    assert kwargs['env_key'] == 'OLLAMA_API_KEY'
    assert [m['id'] for m in args[3]] == ['qwen3:8b', 'qwen3.5:4b']


def test_import_skips_existing_and_without_models(bridge, dsh_home, monkeypatch):
    monkeypatch.setattr(config, 'get_providers',
                        lambda: [{'name': 'ollama', 'models': [{'id': 'x', 'label': 'x'}]}])
    added = []
    monkeypatch.setattr(config, 'add_provider', lambda *a, **k: added.append(a[0]))

    res = bridge.import_dsh_providers()

    assert res['imported'] == ['mimo']
    assert any(s['name'] == 'ollama' and 'existe' in s['reason'] for s in res['skipped'])


def test_get_dsh_providers_reports_state(bridge, dsh_home, monkeypatch):
    monkeypatch.setattr(config, 'get_providers', lambda: [{'name': 'mimo', 'models': []}])
    data = bridge.get_dsh_providers()
    assert data['ok'] is True
    by_name = {p['name']: p for p in data['providers']}
    assert by_name['mimo']['already'] is True
    assert by_name['mimo']['model_count'] == 1
    assert by_name['ollama']['already'] is False

def test_bare_host_base_url_gets_v1(tmp_path, monkeypatch):
    root = tmp_path / '.dsh'
    profile = root / 'profiles' / 'desktop'
    profile.mkdir(parents=True)
    (profile / 'cordis.patch.yml').write_text('''
- id: llm-pi-ai
  name: "@deepseek-ai/dsh-llm-pi-ai"
  config:
    providers:
      claude:
        displayName: claude-ss.ia.br
        apiKeyEnv: CLAUDE_API_KEY
        baseURL: https://claude-ss.ia.br
        models:
          - {id: claude-sonnet-5, name: Claude Sonnet 5}
''', 'utf-8')
    monkeypatch.setenv('AI_BRIDGE_DSH_HOME', str(root))

    providers = dsh_import.read_providers()

    assert providers[0]['base_url'] == 'https://claude-ss.ia.br/v1'
