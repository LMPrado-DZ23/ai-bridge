"""Smoke test de integração desktop (Windows).

Abre a janela real do AI Bridge, exercita minimizar/restaurar/maximizar/
geometria/bandeja e grava o resultado em JSON. Não substitui teste de UI
manual, mas dá evidência repetível sem depender de clique humano.

Uso:
    .venv\\Scripts\\python.exe scripts\\desktop_smoke.py [--out resultado.json]
"""
import argparse
import ctypes
import json
import sys
import threading
import time
import traceback
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webview  # noqa: E402

from ai_bridge import proxy  # noqa: E402
from ai_bridge.bridge import Bridge  # noqa: E402


def _rect(title: str):
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    if not hwnd:
        return None
    r = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(r))
    return {'x': r.left, 'y': r.top, 'w': r.right - r.left, 'h': r.bottom - r.top}


def _iconic(title: str) -> bool:
    hwnd = ctypes.windll.user32.FindWindowW(None, title)
    return bool(hwnd) and bool(ctypes.windll.user32.IsIconic(hwnd))


def run(out_path: Path) -> int:
    results = {'ok': False, 'steps': []}

    def step(name, **data):
        results['steps'].append({'step': name, **data})

    port = proxy.start()
    step('proxy', port=port, running=proxy.is_running())

    bridge = Bridge()
    window = webview.create_window(
        'AI Bridge Smoke', url=(ROOT / 'ai_bridge' / 'ui' / 'index.html').as_uri(),
        js_api=bridge, width=700, height=900, frameless=True, resizable=True,
    )
    bridge.set_window(window)
    tray = None

    def loaded():
        nonlocal tray
        try:
            time.sleep(1.5)
            step('geometry', **(bridge.get_window_geometry() or {}))
            first = _rect('AI Bridge Smoke')

            bridge.minimize()
            time.sleep(0.6)
            step('minimize', iconic=_iconic('AI Bridge Smoke'))

            window.show()
            window.restore()
            time.sleep(0.6)
            step('restore', rect=_rect('AI Bridge Smoke'))

            maxed = bridge.maximize_window()
            time.sleep(0.7)
            step('maximize', result=maxed, rect=_rect('AI Bridge Smoke'))

            normal = bridge.maximize_window()
            time.sleep(0.7)
            back = _rect('AI Bridge Smoke')
            step('unmaximize', result=normal, rect=back)

            geo = bridge.set_window_geometry(120, 140, 650, 820)
            time.sleep(0.6)
            step('resize', result=geo, rect=_rect('AI Bridge Smoke'))

            try:
                import pystray
                tray = pystray.Icon('ab-smoke', _tray_image(), 'AI Bridge Smoke')
                step('tray_created', ok=True)
            except Exception as exc:  # noqa: BLE001 - registrado no relatório
                step('tray_created', ok=False, error=str(exc))

            size_ok = bool(first and first['w'] > 200 and first['h'] > 200)
            results['ok'] = size_ok and (back is not None)
        except Exception:
            results['ok'] = False
            results['error'] = traceback.format_exc()
        finally:
            try:
                if tray:
                    tray.stop()
            except Exception:
                pass
            threading.Timer(0.5, window.destroy).start()

    def _tray_image():
        from PIL import Image
        icon = ROOT / 'ai_bridge' / 'ui' / 'assets' / 'icons' / 'ai-bridge.ico'
        with Image.open(icon) as img:
            return img.convert('RGBA').resize((64, 64))

    window.events.loaded += loaded
    webview.start()

    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding='utf-8')
    return 0 if results['ok'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='desktop-smoke.json')
    args = parser.parse_args()
    raise SystemExit(run(Path(args.out)))
