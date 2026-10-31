"""Teste de conexão de provedor com cookie (sonda real de endpoint)."""
from ai_bridge import bridge as bridge_mod
from ai_bridge import config


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


def _provider(cookie='sid=ok'):
    config.add_provider('CookieProbe', 'http://127.0.0.1:9/v1', '', [{'id': 'm1'}],
                        auth={'kind': 'cookie'}, cookie=cookie)


def _with_cookie(monkeypatch):
    monkeypatch.setattr(config, 'get_cookie', lambda name: 'sid=ok')


def test_cookie_probe_reads_models(monkeypatch):
    _provider()
    _with_cookie(monkeypatch)
    monkeypatch.setattr(bridge_mod.httpx, 'get',
                        lambda *a, **k: FakeResponse(200, {'data': [{'id': 'm1'}, {'id': 'm2'}]}))
    res = bridge_mod.Bridge().test_provider('', '', 'CookieProbe')
    assert res['ok'] is True
    assert res['models'] == 2
    assert 'Cookie aceito' in res['message']


def test_cookie_probe_falls_back_to_inference(monkeypatch):
    _provider()
    _with_cookie(monkeypatch)
    monkeypatch.setattr(bridge_mod.httpx, 'get', lambda *a, **k: FakeResponse(404, {}))
    monkeypatch.setattr(bridge_mod.httpx, 'post', lambda *a, **k: FakeResponse(200, {}))
    res = bridge_mod.Bridge().test_provider('', '', 'CookieProbe')
    assert res['ok'] is True
    assert 'inferência' in res['message']


def test_cookie_probe_reports_refusal(monkeypatch):
    _provider()
    _with_cookie(monkeypatch)
    monkeypatch.setattr(bridge_mod.httpx, 'get', lambda *a, **k: FakeResponse(401, {}))
    monkeypatch.setattr(bridge_mod.httpx, 'post', lambda *a, **k: FakeResponse(403, {}))
    res = bridge_mod.Bridge().test_provider('', '', 'CookieProbe')
    assert res['ok'] is False
    assert 'recusado' in res['error']


def test_cookie_probe_requires_stored_cookie(monkeypatch):
    # provedor sem cookie no keyring
    config.add_provider('SemCookie', 'http://127.0.0.1:9/v1', '', [{'id': 'm1'}],
                        auth={'kind': 'cookie'}, cookie='x')
    # simula keyring vazio (conftest já devolve '' para _get_key)
    res = bridge_mod.Bridge().test_provider('', '', 'SemCookie')
    assert res['ok'] is False
    assert res.get('auth_required') is True
