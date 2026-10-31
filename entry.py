import sys
import os
import logging
import threading
from pathlib import Path

logging.basicConfig(level=logging.WARNING)


def _ui_url() -> str:
    if getattr(sys, 'frozen', False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).parent
    return (base / 'ai_bridge' / 'ui' / 'index.html').as_uri()


def _make_tray_image():
    """Load the same branded AI Bridge icon used by the Windows executable."""
    from PIL import Image, ImageDraw
    icon_path = _brand_icon_path()
    try:
        with Image.open(icon_path) as source:
            return source.convert('RGBA').resize((64, 64), Image.Resampling.LANCZOS)
    except (OSError, ValueError):
        # Keep the tray usable if an installation is missing the optional icon asset.
        size = 64
        img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([1, 1, 62, 62], radius=18, fill=(18, 24, 42, 255), outline=(52, 61, 96, 255), width=2)
        d.line([(15, 38), (25, 28), (31, 26), (39, 30)], fill=(139, 140, 255, 255), width=5)
        d.line([(49, 26), (39, 36), (33, 38), (25, 34)], fill=(67, 215, 232, 255), width=5)
        d.ellipse([11, 34, 19, 42], fill=(139, 140, 255, 255))
        d.ellipse([45, 22, 53, 30], fill=(67, 215, 232, 255))
        return img


def _brand_icon_path() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).parent
    return base / 'ai_bridge' / 'ui' / 'assets' / 'icons' / 'ai-bridge.ico'


def _work_area() -> tuple[int, int] | None:
    """Área útil da tela (sem a barra de tarefas), para não abrir fora do monitor."""
    if sys.platform != 'win32':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if not ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return None
        return (rect.right - rect.left, rect.bottom - rect.top)
    except Exception:
        return None


def _set_app_user_model_id():
    """Agrupa a janela com o próprio app no Windows (ícone/nome da barra)."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('DZ23.AIBridge.1')
    except Exception:
        pass


def _apply_brand_icon(window):
    """Troca o ícone da janela (barra de tarefas) pelo ícone do AI Bridge.

    Rodando do fonte com pythonw.exe, o Windows usa o ícone do interpretador;
    definir o Icon do formulário WinForms corrige isso.
    """
    icon = _brand_icon_path()
    if not icon.is_file():
        return
    try:
        native = getattr(window, 'native', None)
        if native is None:
            return
        from System.Drawing import Icon  # type: ignore[import]
        native.Icon = Icon(str(icon))
    except Exception:
        pass


def main():
    from ai_bridge import proxy
    from ai_bridge.bridge import Bridge

    _set_app_user_model_id()

    # Start proxy before creating the window so the port is ready
    proxy.start()

    import webview  # type: ignore[import]

    bridge = Bridge()

    # "--tray" abre direto na bandeja (sem janela), para atalho do menu Iniciar.
    start_hidden = any(arg in sys.argv for arg in ('--tray', '--hidden'))

    # Janela alta e estreita (destinos um embaixo do outro), limitada à área útil
    # do monitor para nunca abrir parte fora da tela.
    width, height = 680, 1516
    area = _work_area()
    if area:
        width = min(width, max(560, area[0] - 40))
        height = min(height, max(520, area[1] - 40))

    window = webview.create_window(
        title='AI Bridge',
        url=_ui_url(),
        js_api=bridge,
        width=width,
        height=height,
        min_size=(560, 480),
        resizable=True,
        frameless=True,
        easy_drag=False,
        hidden=start_hidden,
        background_color='#0c0c10',
    )

    bridge.set_window(window)

    # ── System tray ───────────────────────────────────────────────────────────
    tray = None
    try:
        import pystray  # type: ignore[import]

        def _show(_icon=None, _item=None):
            window.show()

        def _quit(_icon=None, _item=None):
            bridge.quit()

        tray = pystray.Icon(
            'ai-bridge',
            _make_tray_image(),
            'AI Bridge',
            pystray.Menu(
                pystray.MenuItem('Mostrar', _show, default=True),
                pystray.MenuItem('Sair', _quit),
            ),
        )
        bridge.set_tray(tray)

        # Native close (including ALT+F4) exits instead of leaving a hidden process.
        def _on_closing():
            nonlocal tray
            current_tray, tray = tray, None
            if current_tray:
                try:
                    current_tray.stop()
                except Exception:
                    pass
            return True

        window.events.closing += _on_closing

        window.events.loaded += lambda: _apply_brand_icon(window)
        threading.Thread(target=tray.run, daemon=True, name='ai-bridge-tray').start()
    except ImportError:
        pass  # pystray/PIL unavailable — close button destroys the window normally

    webview.start(debug=('--debug' in sys.argv))

    if tray:
        tray.stop()


if __name__ == '__main__':
    main()
