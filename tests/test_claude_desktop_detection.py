"""Regression tests for Claude Desktop MSIX detection and supported gateway config."""
import json

from ai_bridge import claude_desktop, claude_desktop_gateway


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


class FakeKey:
    def __init__(self, store, identity):
        self.store = store
        self.identity = identity

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_LOCAL_MACHINE = "HKLM"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_DWORD = 4

    def __init__(self):
        self.store = {}

    def OpenKey(self, root, path, reserved=0, access=0):
        identity = (root, path)
        if identity not in self.store:
            raise FileNotFoundError(path)
        return FakeKey(self.store, identity)

    def CreateKeyEx(self, root, path, reserved=0, access=0):
        identity = (root, path)
        self.store.setdefault(identity, {})
        return FakeKey(self.store, identity)

    def EnumValue(self, key, index):
        values = list(key.store[key.identity].items())
        if index >= len(values):
            raise OSError("no more values")
        name, (value, kind) = values[index]
        return name, value, kind

    def SetValueEx(self, key, name, reserved, kind, value):
        key.store[key.identity][name] = (value, kind)

    def DeleteValue(self, key, name):
        if name not in key.store[key.identity]:
            raise FileNotFoundError(name)
        del key.store[key.identity][name]

    def CloseKey(self, key):
        pass


def _prepare_gateway_test(tmp_path, monkeypatch):
    fake = FakeWinreg()
    local = tmp_path / "Local"
    backup_dir = local / "AI-Bridge" / "backups"
    app_config = local / "Claude-3p" / "claude_desktop_config.json"
    app_config.parent.mkdir(parents=True)
    app_config.write_text(json.dumps({"preferences": {"theme": "dark"}, "deploymentMode": "1p"}), encoding="utf-8")
    monkeypatch.setattr(claude_desktop_gateway, "_registry", lambda: fake)
    monkeypatch.setattr(claude_desktop_gateway, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(claude_desktop_gateway, "_BACKUP_FILE", backup_dir / "claude-desktop-policy.json")
    monkeypatch.setattr(claude_desktop_gateway, "_APP_CONFIG", app_config)
    return fake, app_config, backup_dir


def test_connect_uses_gateway_settings_and_preserves_app_preferences(tmp_path, monkeypatch):
    fake, app_config, backup_dir = _prepare_gateway_test(tmp_path, monkeypatch)
    result = claude_desktop_gateway.configure(38771, [
        {"name": "DeepSeek/deepseek-chat", "labelOverride": "DeepSeek Chat · DeepSeek"}
    ])

    values = fake.store[("HKCU", r"SOFTWARE\Policies\Claude")]
    assert result["ok"] is True
    assert values["inferenceProvider"] == ("gateway", fake.REG_SZ)
    assert values["inferenceGatewayBaseUrl"] == ("http://127.0.0.1:38771", fake.REG_SZ)
    assert values["inferenceGatewayApiKey"] == ("ai-bridge-local", fake.REG_SZ)
    assert values["inferenceCredentialKind"] == ("static", fake.REG_SZ)
    assert values["modelDiscoveryEnabled"] == ("false", fake.REG_SZ)
    assert json.loads(values["inferenceModels"][0])[0]["name"] == "DeepSeek/deepseek-chat"
    app = json.loads(app_config.read_text(encoding="utf-8"))
    assert app["preferences"]["theme"] == "dark"
    assert app["deploymentMode"] == "3p"
    assert (backup_dir / "claude-desktop-policy.json").exists()


def test_disconnect_restores_existing_user_policy_and_original_mode(tmp_path, monkeypatch):
    fake, app_config, backup_dir = _prepare_gateway_test(tmp_path, monkeypatch)
    policy_path = r"SOFTWARE\Policies\Claude"
    fake.store[("HKCU", policy_path)] = {
        "inferenceProvider": ("old-provider", fake.REG_SZ),
        "inferenceGatewayBaseUrl": ("https://old.example", fake.REG_SZ),
        "unrelatedSetting": ("keep-me", fake.REG_SZ),
    }
    claude_desktop_gateway.configure(38771, [
        {"name": "DeepSeek/deepseek-chat", "labelOverride": "Test model"}
    ])
    claude_desktop_gateway.disconnect()

    values = fake.store[("HKCU", policy_path)]
    assert values["inferenceProvider"] == ("old-provider", fake.REG_SZ)
    assert values["inferenceGatewayBaseUrl"] == ("https://old.example", fake.REG_SZ)
    assert values["unrelatedSetting"] == ("keep-me", fake.REG_SZ)
    app = json.loads(app_config.read_text(encoding="utf-8"))
    assert app["preferences"]["theme"] == "dark"
    assert app["deploymentMode"] == "1p"  # prior app mode was restored
    assert not (backup_dir / "claude-desktop-policy.json").exists()


def test_connect_refuses_machine_managed_gateway(tmp_path, monkeypatch):
    fake, app_config, backup_dir = _prepare_gateway_test(tmp_path, monkeypatch)
    fake.store[("HKLM", r"SOFTWARE\Policies\Claude")] = {
        "inferenceProvider": ("gateway", fake.REG_SZ),
        "inferenceGatewayBaseUrl": ("https://managed.example", fake.REG_SZ),
    }
    try:
        claude_desktop_gateway.configure(38771, [
            {"name": "DeepSeek/deepseek-chat", "labelOverride": "Test model"}
        ])
    except RuntimeError as exc:
        assert "gerenciado" in str(exc)
    else:
        raise AssertionError("machine-managed gateway must not be overwritten")
    assert ("HKCU", r"SOFTWARE\Policies\Claude") not in fake.store


def test_disconnect_preserves_gateway_not_owned_by_ai_bridge(tmp_path, monkeypatch):
    fake, app_config, backup_dir = _prepare_gateway_test(tmp_path, monkeypatch)
    policy_path = r"SOFTWARE\Policies\Claude"
    fake.store[("HKCU", policy_path)] = {
        "inferenceProvider": ("gateway", fake.REG_SZ),
        "inferenceGatewayBaseUrl": ("https://external.example", fake.REG_SZ),
        "inferenceGatewayApiKey": ("external-secret", fake.REG_SZ),
    }

    try:
        claude_desktop_gateway.disconnect()
    except RuntimeError as exc:
        assert "foi preservada" in str(exc)
    else:
        raise AssertionError("external gateway must not be removed without an AI Bridge backup")

    values = fake.store[("HKCU", policy_path)]
    assert values["inferenceGatewayBaseUrl"] == ("https://external.example", fake.REG_SZ)
    assert values["inferenceGatewayApiKey"] == ("external-secret", fake.REG_SZ)
