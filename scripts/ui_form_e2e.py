"""E2E da tela de formulário com um upstream falso real.

Exercita o caminho do usuário sem depender de conta: seleciona provedor no
catálogo, preenche campos, busca modelos, testa conexão, salva e remove.

Uso:  .venv\\Scripts\\python.exe scripts\\ui_form_e2e.py [--out e2e.json]
"""
import argparse
import json
import sys
import threading
import time
import traceback
from pathlib import Path

from flask import Flask, jsonify, request
from werkzeug.serving import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from ai_bridge import config, proxy  # noqa: E402
from ai_bridge.bridge import Bridge  # noqa: E402

NAME = 'E2E Fake'


def _start_upstream():
    app = Flask('e2e-upstream')

    @app.get('/v1/models')
    def models():
        return jsonify({'data': [{'id': 'm1'}, {'id': 'm2'}]})

    @app.post('/v1/chat/completions')
    def chat():
        return jsonify({'id': 'x', 'choices': [{'message': {'role': 'assistant', 'content': 'ok'}}]})

    server = make_server('127.0.0.1', 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(out_path: Path) -> int:
    result = {'ok': False, 'steps': []}

    def step(name, **data):
        result['steps'].append({'step': name, **data})

    upstream = _start_upstream()
    base = f'http://127.0.0.1:{upstream.server_port}/v1'
    proxy.start()
    step('upstream', base=base, proxy=proxy.get_port())

    bridge = Bridge()
    window = webview.create_window('AI Bridge E2E', url=(ROOT / 'ai_bridge' / 'ui' / 'index.html').as_uri(),
                                   js_api=bridge, width=760, height=900, frameless=True)
    bridge.set_window(window)

    def loaded():
        try:
            time.sleep(2)
            window.evaluate_js("go('add')")
            time.sleep(0.5)

            # 1) clique no catálogo
            window.evaluate_js("document.querySelector('.ab-catalog__item').click()")
            time.sleep(0.8)
            state1 = window.evaluate_js("""
            JSON.stringify({step2: document.getElementById('wizard-layout').classList.contains('is-step2'),
                            summary: document.getElementById('selected-name').textContent})
            """)
            step('catalog_click', **(json.loads(state1) if isinstance(state1, str) else state1))

            # 2) preencher e buscar modelos
            window.evaluate_js(f"""
            (() => {{
              document.getElementById('f-name').value = {NAME!r};
              document.getElementById('f-url').value = {base!r};
              document.getElementById('f-key').value = 'test';
              document.getElementById('f-auth-kind').value = 'api_key';
              document.getElementById('f-protocol').value = 'chat';
              document.getElementById('f-models').value = 'm1|M1\\nm2|M2';
              document.getElementById('btn-fetch-models').click();
            }})()
            """)
            time.sleep(1.5)
            state2 = window.evaluate_js("""
            JSON.stringify({status: document.getElementById('models-status').textContent,
                            picker: document.querySelectorAll('#model-picker input[data-model]').length})
            """)
            step('fetch_models', **(json.loads(state2) if isinstance(state2, str) else state2))

            # 3) testar conexão
            window.evaluate_js("document.getElementById('btn-test').click()")
            time.sleep(1.5)
            state3 = window.evaluate_js("""
            JSON.stringify({text: document.getElementById('test-result').textContent,
                            ok: document.getElementById('test-result').className})
            """)
            step('test_connection', **(json.loads(state3) if isinstance(state3, str) else state3))

            # 4) salvar
            window.evaluate_js("document.getElementById('add-form').requestSubmit()")
            time.sleep(1.5)
            saved = config.get_provider(NAME)
            step('save', saved=bool(saved), models=len((saved or {}).get('models', [])))

            picker = result['steps'][2].get('picker', 0)
            result['ok'] = bool(saved) and result['steps'][1].get('step2') is True and picker > 0
        except Exception:
            result['ok'] = False
            result['error'] = traceback.format_exc()
        finally:
            try:
                config.remove_provider(NAME)
            except Exception:
                pass
            try:
                upstream.shutdown()
            except Exception:
                pass
            threading.Timer(0.6, window.destroy).start()

    window.events.loaded += loaded
    webview.start()
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='form-e2e.json')
    args = parser.parse_args()
    raise SystemExit(run(Path(args.out)))
