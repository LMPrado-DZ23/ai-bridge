"""Métricas do proxy e tela de monitoramento."""
from pathlib import Path

from ai_bridge import bridge as bridge_mod
from ai_bridge import proxy


def test_health_is_not_counted():
    proxy.reset_metrics()
    client = proxy.app.test_client()
    assert client.get('/health').status_code == 200
    data = proxy.get_metrics()
    assert data['requests'] == 0
    assert data['events'] == []


def test_requests_are_recorded_with_status_and_latency():
    proxy.reset_metrics()
    client = proxy.app.test_client()
    # modelo inexistente: o proxy responde erro, mas a requisição é contabilizada
    response = client.post('/v1/chat/completions',
                           json={'model': 'NaoExiste/modelo', 'messages': []})
    assert response.status_code >= 400

    data = proxy.get_metrics()
    assert data['requests'] == 1
    assert data['errors'] == 1
    assert data['events'][0]['path'] == '/v1/chat/completions'
    assert data['events'][0]['status'] == response.status_code
    assert data['avg_ms'] >= 0


def test_metrics_snapshot_shape_and_reset():
    proxy.reset_metrics()
    client = proxy.app.test_client()
    client.get('/v1/models')
    data = proxy.get_metrics()
    for key in ('requests', 'errors', 'avg_ms', 'uptime_s', 'by_path', 'events'):
        assert key in data
    assert '/v1/models' in data['by_path']
    proxy.reset_metrics()
    assert proxy.get_metrics()['requests'] == 0


def test_bridge_exposes_metrics():
    proxy.reset_metrics()
    res = bridge_mod.Bridge().get_metrics()
    assert res['ok'] is True
    assert 'requests' in res and 'port' in res and 'running' in res


def test_monitor_ui_is_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'ai_bridge' / 'ui' / 'index.html').read_text(encoding='utf-8')
    js = (root / 'ai_bridge' / 'ui' / 'app.js').read_text(encoding='utf-8')
    assert 'data-screen="monitor"' in html
    assert 'id="btn-monitor"' in html
    assert 'id="monitor-stats"' in html
    assert 'id="monitor-events"' in html
    assert 'renderMonitor' in js and "api('get_metrics')" in js
