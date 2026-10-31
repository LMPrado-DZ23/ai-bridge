"""Log de eventos: rotação, saneamento e integração com o proxy."""
import json

from ai_bridge import eventlog, proxy


def _setup(tmp_path, monkeypatch, max_bytes=400):
    monkeypatch.setattr(eventlog, 'LOG_DIR', tmp_path / 'logs')
    monkeypatch.setattr(eventlog, 'MAX_BYTES', max_bytes)
    eventlog.clear()


def test_append_and_read_recent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    eventlog.append({'path': '/v1/models', 'method': 'GET', 'status': 200, 'ms': 3.2,
                     'provider': 'DeepSeek', 'model': 'DeepSeek/x'})
    events = eventlog.read_recent()
    assert len(events) == 1
    assert events[0]['path'] == '/v1/models'
    assert events[0]['ts']


def test_extra_fields_are_dropped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    eventlog.append({'path': '/x', 'prompt': 'segredo', 'authorization': 'Bearer abc'})
    raw = (tmp_path / 'logs' / 'events.jsonl').read_text(encoding='utf-8')
    assert 'segredo' not in raw
    assert 'Bearer' not in raw


def test_rotation_keeps_bounded_files(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, max_bytes=120)
    for i in range(30):
        eventlog.append({'path': f'/p{i}', 'method': 'GET', 'status': 200, 'ms': 1})
    files = sorted(p.name for p in (tmp_path / 'logs').iterdir())
    assert 'events.jsonl' in files
    assert len(files) <= eventlog.KEEP_FILES
    recent = eventlog.read_recent(5)
    assert 1 <= len(recent) <= eventlog.KEEP_FILES


def test_read_recent_on_missing_dir_returns_empty(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert eventlog.read_recent() == []


def test_proxy_writes_event_log(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    proxy.reset_metrics()
    client = proxy.app.test_client()
    client.post('/v1/chat/completions', json={'model': 'DeepSeek/z', 'messages': []})
    events = eventlog.read_recent()
    assert events and events[0]['path'] == '/v1/chat/completions'
    assert events[0]['provider'] == 'DeepSeek'
    assert 'prompt' not in events[0]
