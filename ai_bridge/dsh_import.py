"""Importa provedores e modelos do perfil do DeepSeek Harness (DSH).

O DSH descreve provedores OpenAI-compatible no patch do perfil
(``~/.dsh/profiles/<perfil>/cordis.patch.yml``), na entrada ``llm-pi-ai``::

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

Este módulo só lê configuração (nunca segredos: o YAML referencia variáveis de
ambiente pelo nome) e devolve os provedores utilizáveis pelo AI Bridge.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

log = logging.getLogger(__name__)

PATCH_FILENAMES = ('cordis.patch.yml', 'cordis.patch.yaml')
DEFAULT_PROFILE = 'desktop'


def dsh_home() -> Path:
    override = os.environ.get('AI_BRIDGE_DSH_HOME') or os.environ.get('DSH_HOME')
    return Path(override) if override else Path.home() / '.dsh'


def profile_dirs() -> list[Path]:
    root = dsh_home() / 'profiles'
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name)


def _patch_files(profile: Optional[str] = None) -> list[Path]:
    dirs = profile_dirs()
    if profile:
        dirs = [d for d in dirs if d.name == profile] or dirs
    else:
        # Prefer the desktop profile, then the others.
        dirs.sort(key=lambda d: (d.name != DEFAULT_PROFILE, d.name))
    files = []
    for directory in dirs:
        for filename in PATCH_FILENAMES:
            candidate = directory / filename
            if candidate.is_file():
                files.append(candidate)
    return files


def _load_yaml(path: Path):
    try:
        return yaml.safe_load(path.read_text('utf-8'))
    except (OSError, yaml.YAMLError) as exc:
        log.warning('dsh_import: não consegui ler %s: %s', path, exc)
        return None


def _providers_from_patch(payload) -> dict:
    """Return the ``llm-pi-ai`` providers mapping from one patch file."""
    if not isinstance(payload, list):
        return {}
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        if entry.get('id') == 'llm-pi-ai' or entry.get('name') == '@deepseek-ai/dsh-llm-pi-ai':
            config = entry.get('config') or {}
            providers = config.get('providers') if isinstance(config, dict) else None
            if isinstance(providers, dict):
                return providers
    return {}


def _models(models) -> list[dict]:
    result = []
    for model in models or []:
        if not isinstance(model, dict) or not model.get('id'):
            continue
        result.append({
            'id': str(model['id']),
            'label': str(model.get('name') or model['id']),
        })
    return result


def _normalize_base_url(base_url: str) -> str:
    """DSH assumes /v1 on bare hosts; the bridge needs the path explicit."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(base_url.rstrip('/'))
    path = parts.path.rstrip('/')
    if not path:
        path = '/v1'
    return urlunsplit((parts.scheme, parts.netloc, path, '', ''))


def read_providers(profile: Optional[str] = None) -> list[dict]:
    """Read DSH providers that carry a base URL (the ones AI Bridge can proxy)."""
    found: dict[str, dict] = {}
    for path in _patch_files(profile):
        providers = _providers_from_patch(_load_yaml(path))
        for name, data in providers.items():
            if not isinstance(data, dict):
                continue
            base_url = str(data.get('baseURL') or data.get('base_url') or '').strip()
            if not base_url:
                continue
            found.setdefault(name, {
                'name': str(name),
                'display': str(data.get('displayName') or name),
                'base_url': _normalize_base_url(base_url),
                'env_key': str(data.get('apiKeyEnv') or data.get('api_key_env') or ''),
                'models': _models(data.get('models')),
                'source_file': str(path),
            })
        if found:
            break
    return [found[name] for name in sorted(found)]


def env_available(env_key: str) -> bool:
    if not env_key:
        return True  # provedores locais (Ollama) não exigem chave
    return bool(os.environ.get(env_key))
