from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "ai_bridge" / "ui" / "assets" / "icons" / "ai-bridge.ico"


def test_branded_icon_is_valid_multiresolution_ico():
    assert ICON.is_file()
    with Image.open(ICON) as image:
        assert image.format == "ICO"
        assert image.size[0] >= 64
        assert image.size[1] >= 64


def test_windows_executable_and_tray_use_branded_icon():
    spec = (ROOT / "build.spec").read_text(encoding="utf-8")
    entry = (ROOT / "entry.py").read_text(encoding="utf-8")
    assert "icon='ai_bridge/ui/assets/icons/ai-bridge.ico'" in spec
    assert "ai-bridge.ico" in entry


def test_close_button_calls_real_quit_api():
    source = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "if (api?.quit) api.quit()" in source
    assert "close_to_tray()" not in source


def test_native_close_does_not_hide_to_tray():
    source = (ROOT / "entry.py").read_text(encoding="utf-8")
    assert "return True" in source
    assert "window.hide()" not in source


def test_mode_switch_ui_has_no_second_confirmation_dialog():
    source = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    assert "window.confirm(" not in source
    assert "api('activate_target', _currentTarget, mode)" in source
    assert "let _modeSwitchPending = false" in source

def test_tray_button_hides_window_without_quitting():
    js = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "ai_bridge" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-tray"' in html
    assert "btn-tray" in js
    assert "if (api?.hide_window) api.hide_window()" in js


def test_entry_supports_start_hidden_for_tray_shortcut():
    source = (ROOT / "entry.py").read_text(encoding="utf-8")
    assert "'--tray'" in source
    assert "hidden=start_hidden" in source

def test_add_screen_has_provider_catalog_and_protocol():
    js = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "ai_bridge" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="provider-catalog"' in html
    assert 'id="catalog-search"' in html
    assert 'id="f-protocol"' in html
    assert "api('get_catalog')" in js
    assert "applyCatalogEntry" in js
    assert "protocol || null" in js

def test_add_screen_has_dsh_import_button():
    js = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "ai_bridge" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="btn-import-dsh"' in html
    assert "api('import_dsh_providers')" in js

def test_form_has_env_key_field_and_submits_it():
    js = (ROOT / "ai_bridge" / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "ai_bridge" / "ui" / "index.html").read_text(encoding="utf-8")
    assert 'id="f-env-key"' in html
    assert "envKey || null" in js
