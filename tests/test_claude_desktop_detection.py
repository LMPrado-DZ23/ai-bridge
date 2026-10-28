"""Regression tests for Claude Desktop Windows/MSIX detection."""
from pathlib import Path

from ai_bridge import claude_desktop


def test_resolve_uses_existing_msix_user_data_config(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    appdata = tmp_path / "Roaming"
    custom = local / "Claude-Data" / "claude_pzs8sxrjxfjjc"
    custom.mkdir(parents=True)
    (custom / "claude_desktop_config.json").write_text('{"preferences": {}}', encoding="utf-8")
    (appdata / "Claude").mkdir(parents=True)
    (appdata / "Claude" / "claude_desktop_config.json").write_text('{}', encoding="utf-8")
    monkeypatch.setattr(claude_desktop.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(appdata))

    assert claude_desktop._resolve_cfg_dir() == custom


def test_detects_msix_install_without_legacy_appdata_config(tmp_path, monkeypatch):
    local = tmp_path / "Local"
    package_data = local / "Packages" / "Claude_pzs8sxrjxfjjc"
    package_data.mkdir(parents=True)
    monkeypatch.setattr(claude_desktop.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setattr(claude_desktop, "_CFG_DIR", tmp_path / "Roaming" / "Claude")

    assert claude_desktop._is_installed() is True


def test_connect_preserves_and_backs_up_existing_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "Claude-Data" / "claude_store"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "claude_desktop_config.json"
    original = {"preferences": {"theme": "dark"}, "coworkUserFilesPath": "C:/Users/test"}
    import json
    config_file.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(claude_desktop, "_CFG_DIR", config_dir)
    monkeypatch.setattr(claude_desktop, "_CFG_FILE", config_file)
    monkeypatch.setattr(claude_desktop, "_set_win_env", lambda *args: None)
    monkeypatch.setattr(claude_desktop, "_set_mac_env", lambda *args: None)

    claude_desktop.connect(38771)

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved["preferences"] == original["preferences"]
    assert saved["coworkUserFilesPath"] == original["coworkUserFilesPath"]
    assert saved["_ai_bridge"] == {"port": 38771}
    backups = list(config_dir.glob("claude_desktop_config.ai-bridge-backup-*.json"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_connect_refuses_to_overwrite_invalid_config(tmp_path, monkeypatch):
    config_dir = tmp_path / "Claude-Data" / "claude_store"
    config_dir.mkdir(parents=True)
    config_file = config_dir / "claude_desktop_config.json"
    config_file.write_text("{not-json", encoding="utf-8")
    monkeypatch.setattr(claude_desktop, "_CFG_DIR", config_dir)
    monkeypatch.setattr(claude_desktop, "_CFG_FILE", config_file)
    monkeypatch.setattr(claude_desktop, "_set_win_env", lambda *args: None)
    monkeypatch.setattr(claude_desktop, "_set_mac_env", lambda *args: None)

    try:
        claude_desktop.connect(38771)
    except RuntimeError as exc:
        assert "arquivo preservado" in str(exc)
    else:
        raise AssertionError("invalid config should not be overwritten")

    assert config_file.read_text(encoding="utf-8") == "{not-json"
