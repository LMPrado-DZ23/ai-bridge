"""Preferências de desktop, autostart reversível e fechamento configurável."""
import json
from pathlib import Path

from ai_bridge import bridge as bridge_mod
from ai_bridge import config


def test_corrupt_config_is_preserved_and_defaults_are_used(tmp_path):
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.CONFIG_FILE.write_text('{ isto não é json', encoding='utf-8')

    data = config.load()

    assert isinstance(data, dict)
    backups = list(config.CONFIG_DIR.glob('config.corrupt-*.json'))
    assert backups, 'configuração corrompida deve ser preservada'
    assert 'isto não é json' in backups[0].read_text(encoding='utf-8')
    assert not config.CONFIG_FILE.exists()


def test_settings_defaults_and_update():
    assert config.get_settings() == {
        'close_to_tray': False,
        'start_with_windows': False,
        'start_minimized': False,
    }
    updated = config.update_settings(close_to_tray=True)
    assert updated['close_to_tray'] is True
    assert config.get_settings()['close_to_tray'] is True
    stored = json.loads(config.CONFIG_FILE.read_text(encoding='utf-8'))
    assert stored['settings']['close_to_tray'] is True


def test_set_setting_applies_autostart(monkeypatch):
    calls = []
    monkeypatch.setattr(bridge_mod, '_set_autostart', lambda enabled: calls.append(enabled) or {'ok': True})
    monkeypatch.setattr(bridge_mod, '_autostart_enabled', lambda: True)

    b = bridge_mod.Bridge()
    res = b.set_setting('start_with_windows', True)

    assert res['ok'] is True
    assert calls == [True]
    assert res['autostart'] is True
    assert config.get_settings()['start_with_windows'] is True


def test_set_setting_rejects_unknown_key():
    res = bridge_mod.Bridge().set_setting('rm_rf', True)
    assert res['ok'] is False


def test_request_close_hides_when_configured(monkeypatch):
    config.update_settings(close_to_tray=True)
    b = bridge_mod.Bridge()
    hidden, quit_called = [], []
    b.hide_window = lambda: hidden.append(True)
    b.quit = lambda: quit_called.append(True)

    res = b.request_close()

    assert res == {'ok': True, 'closed': False}
    assert hidden == [True]
    assert quit_called == []


def test_request_close_quits_when_not_configured(monkeypatch):
    config.update_settings(close_to_tray=False)
    b = bridge_mod.Bridge()
    hidden, quit_called = [], []
    b.hide_window = lambda: hidden.append(True)
    b.quit = lambda: quit_called.append(True)

    res = b.request_close()

    assert res == {'ok': True, 'closed': True}
    assert hidden == []
    assert quit_called == [True]


def test_autostart_command_uses_tray_flag():
    command = bridge_mod._autostart_command()
    assert command.endswith('--tray')
    assert 'entry.py' in command or 'AI-Bridge' in command


def test_settings_ui_is_wired():
    root = Path(__file__).resolve().parents[1]
    html = (root / 'ai_bridge' / 'ui' / 'index.html').read_text(encoding='utf-8')
    js = (root / 'ai_bridge' / 'ui' / 'app.js').read_text(encoding='utf-8')
    assert 'data-screen="settings"' in html
    assert 'id="btn-settings"' in html
    assert 'id="set-start-with-windows"' in html
    assert 'id="set-close-to-tray"' in html
    assert "go('settings')" in js
    assert 'get_settings' in js and 'set_setting' in js
    assert 'api.request_close' in js
