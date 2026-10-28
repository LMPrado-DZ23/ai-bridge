import json
import os
from pathlib import Path
from typing import Optional

CONFIG_DIR = Path.home() / '.ai-bridge'
CONFIG_FILE = CONFIG_DIR / 'config.json'
DEFAULT_PORT = 38771


def _default() -> dict:
    return {'providers': [], 'port': DEFAULT_PORT}


def load() -> dict:
    if not CONFIG_FILE.exists():
        return _default()
    try:
        return json.loads(CONFIG_FILE.read_text('utf-8'))
    except Exception:
        return _default()


def save(data: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_DIR / f'.tmp-{os.getpid()}'
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), 'utf-8')
    tmp.replace(CONFIG_FILE)


def get_providers() -> list:
    return load().get('providers', [])


def get_port() -> int:
    return load().get('port', DEFAULT_PORT)


def add_provider(name: str, base_url: str, api_key: str, models: list):
    data = load()
    providers = [p for p in data.get('providers', []) if p['name'] != name]
    providers.append({
        'name': name,
        'base_url': base_url.rstrip('/'),
        'api_key': api_key,
        'models': models,
    })
    data['providers'] = providers
    save(data)


def remove_provider(name: str):
    data = load()
    data['providers'] = [p for p in data.get('providers', []) if p['name'] != name]
    save(data)


def get_provider_for_model(model: str) -> Optional[dict]:
    for p in get_providers():
        for m in p.get('models', []):
            label = m.get('label', m['id'])
            if model in (
                f"{p['name']}/{m['id']}",   # Claude Code format: Provider/id
                m['id'],                      # plain id
                f"{label} · {p['name']}",    # Codex picker format: Label · Provider
            ):
                return p
    return None


def get_model_id(model: str) -> Optional[str]:
    """Return the actual model ID (to send to the provider) for any supported format."""
    for p in get_providers():
        for m in p.get('models', []):
            label = m.get('label', m['id'])
            if model in (
                f"{p['name']}/{m['id']}",
                m['id'],
                f"{label} · {p['name']}",
            ):
                return m['id']
    return None


def all_picker_models() -> list:
    result = []
    for p in get_providers():
        for m in p.get('models', []):
            result.append({
                'value': f"{p['name']}/{m['id']}",
                'label': f"{m.get('label', m['id'])} · {p['name']}",
            })
    return result
