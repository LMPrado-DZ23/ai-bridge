"""Guardas de segurança do proxy local."""
from pathlib import Path

from ai_bridge import proxy


def test_proxy_rejects_non_loopback_host():
    proxy.reset_metrics()
    client = proxy.app.test_client()
    response = client.get('/v1/models', base_url='http://evil.example:38771')
    assert response.status_code == 403
    assert 'host' in response.get_json()['error']['message']


def test_proxy_accepts_loopback_hosts():
    client = proxy.app.test_client()
    for host in ('http://127.0.0.1:38771', 'http://localhost:38771'):
        response = client.get('/health', base_url=host)
        assert response.status_code == 200


def test_proxy_binds_only_loopback():
    source = Path(__file__).resolve().parents[1] / 'ai_bridge' / 'proxy.py'
    text = source.read_text(encoding='utf-8')
    assert "s.bind(('127.0.0.1'" in text
    assert "app.run(host='127.0.0.1'" in text
    assert "host='0.0.0.0'" not in text
