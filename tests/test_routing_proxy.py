"""Seleção de provedor por nome no proxy, com upstream falso real (HTTP local)."""
import threading

import pytest
from flask import Flask, Response, jsonify, request
from werkzeug.serving import make_server

from ai_bridge import config, proxy


@pytest.fixture()
def fake_upstream():
    app = Flask('fake-upstream')

    @app.post('/v1/chat/completions')
    def chat():
        body = request.get_json(force=True, silent=True) or {}
        if body.get('stream'):
            def gen():
                yield 'data: {"choices":[{"delta":{"content":"ok"}}]}\n\n'
                yield 'data: [DONE]\n\n'
            return Response(gen(), mimetype='text/event-stream')
        return jsonify({'id': 'x', 'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}]})

    server = make_server('127.0.0.1', 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}/v1'
    server.shutdown()


def _configure(base_url):
    config.add_provider('Fake', base_url, '', [{'id': 'm1', 'label': 'M1'}], protocol='chat')


def _payload(stream=False):
    return {'model': 'm1', 'messages': [{'role': 'user', 'content': 'oi'}], 'stream': stream}


def test_header_selects_provider_without_prefix(fake_upstream):
    _configure(fake_upstream)
    proxy.reset_metrics()
    client = proxy.app.test_client()
    res = client.post('/v1/chat/completions', json=_payload(),
                      headers={'X-AI-Bridge-Provider': 'Fake'})
    assert res.status_code == 200
    assert res.get_json()['choices'][0]['message']['content'] == 'ok'


def test_query_selects_provider(fake_upstream):
    _configure(fake_upstream)
    client = proxy.app.test_client()
    res = client.post('/v1/chat/completions?provider=Fake', json=_payload())
    assert res.status_code == 200


def test_prefix_still_works(fake_upstream):
    _configure(fake_upstream)
    client = proxy.app.test_client()
    res = client.post('/v1/chat/completions', json={**_payload(), 'model': 'Fake/m1'})
    assert res.status_code == 200


def test_unknown_model_still_404(fake_upstream):
    _configure(fake_upstream)
    client = proxy.app.test_client()
    res = client.post('/v1/chat/completions', json={**_payload(), 'model': 'NaoExiste/m1'})
    assert res.status_code == 404


def test_streaming_passthrough_with_provider_header(fake_upstream):
    _configure(fake_upstream)
    client = proxy.app.test_client()
    res = client.post('/v1/chat/completions', json=_payload(stream=True),
                      headers={'X-AI-Bridge-Provider': 'Fake'})
    assert res.status_code == 200
    body = res.get_data(as_text=True)
    assert 'data:' in body and 'ok' in body


def test_selection_is_recorded_by_provider(fake_upstream):
    _configure(fake_upstream)
    proxy.reset_metrics()
    client = proxy.app.test_client()
    client.post('/v1/chat/completions', json=_payload(),
                headers={'X-AI-Bridge-Provider': 'Fake'})
    assert proxy.get_metrics()['by_provider'].get('Fake') == 1
