"""Log de eventos do proxy com rotação.

Grava apenas metadados de requisição (rota, método, status, latência, provedor e
modelo). Nunca grava prompt, corpo de resposta, token, API key ou cookie.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

LOG_DIR = Path.home() / '.ai-bridge' / 'logs'
LOG_NAME = 'events.jsonl'
MAX_BYTES = 1_000_000
KEEP_FILES = 3

FIELDS = ('ts', 'path', 'method', 'status', 'ms', 'provider', 'model')
_lock = threading.Lock()


def _path(seq: int = 0) -> Path:
    return LOG_DIR / (LOG_NAME if seq == 0 else f'events.{seq}.jsonl')


def _rotate():
    # Mantém o arquivo atual + (KEEP_FILES - 1) backups.
    oldest = _path(KEEP_FILES - 1)
    if oldest.exists():
        oldest.unlink()
    for seq in range(KEEP_FILES - 2, 0, -1):
        source = _path(seq)
        if source.exists():
            source.replace(_path(seq + 1))
    if _path(0).exists():
        _path(0).replace(_path(1))


def append(record: dict) -> None:
    """Acrescenta um evento saneado; falhas de I/O nunca derrubam a requisição."""
    clean = {key: record.get(key) for key in FIELDS}
    clean['ts'] = clean.get('ts') or time.time()
    line = json.dumps(clean, ensure_ascii=False)
    with _lock:
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            target = _path(0)
            if target.exists() and target.stat().st_size + len(line) > MAX_BYTES:
                _rotate()
            with target.open('a', encoding='utf-8') as fh:
                fh.write(line + '\n')
        except OSError:
            return


def read_recent(limit: int = 200) -> list[dict]:
    """Últimos eventos do arquivo atual e dos backups, do mais novo ao mais antigo."""
    limit = max(1, min(int(limit), 1000))
    events: list[dict] = []
    for seq in range(KEEP_FILES):
        try:
            lines = _path(seq).read_text(encoding='utf-8').splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except ValueError:
                continue
            if len(events) >= limit:
                return events
    return events


def clear() -> None:
    with _lock:
        for seq in range(KEEP_FILES + 1):
            try:
                _path(seq).unlink()
            except OSError:
                pass
