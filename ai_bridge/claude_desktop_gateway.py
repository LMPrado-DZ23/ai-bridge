"""Supported Claude Desktop third-party inference configuration on Windows."""
import json
import os
import sys
from pathlib import Path

_POLICY_PATH = r"SOFTWARE\Policies\Claude"
_POLICY_NAMES = (
    "inferenceProvider",
    "inferenceGatewayBaseUrl",
    "inferenceGatewayApiKey",
    "inferenceGatewayAuthScheme",
    "inferenceCredentialKind",
    "inferenceModels",
    "modelDiscoveryEnabled",
)
_BACKUP_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "AI-Bridge" / "backups"
_BACKUP_FILE = _BACKUP_DIR / "claude-desktop-policy.json"
_APP_CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Claude-3p" / "claude_desktop_config.json"


def _registry():
    if sys.platform != "win32":
        raise RuntimeError("A configuração automática do Claude Desktop por gateway está implementada para Windows.")
    import winreg
    return winreg


def _read_values(root, path):
    winreg = _registry()
    try:
        key = winreg.OpenKey(root, path, 0, winreg.KEY_READ)
    except FileNotFoundError:
        return False, {}
    values = {}
    with key:
        index = 0
        while True:
            try:
                name, value, value_type = winreg.EnumValue(key, index)
            except OSError:
                break
            values[name] = {"value": value, "type": value_type}
            index += 1
    return True, values


def _write_app_mode(mode):
    path = _APP_CONFIG
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text("utf-8"))
        except Exception as exc:
            raise RuntimeError("A configuração local do Claude Desktop não é JSON válido; arquivo preservado.") from exc
        if not isinstance(data, dict):
            raise RuntimeError("A configuração local do Claude Desktop tem formato inesperado; arquivo preservado.")
    data["deploymentMode"] = mode
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".ai-bridge.tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def configure(port: int, models: list) -> dict:
    """Apply a per-user gateway route without touching Claude sign-in/session data."""
    if not models:
        raise RuntimeError("Adicione e salve ao menos um provedor/modelo antes de conectar o Claude Desktop.")
    winreg = _registry()
    machine_exists, machine_values = _read_values(winreg.HKEY_LOCAL_MACHINE, _POLICY_PATH)
    if machine_exists and any(name in machine_values for name in _POLICY_NAMES):
        raise RuntimeError("O Claude Desktop já tem um gateway gerenciado por política do Windows. O AI Bridge não vai sobrescrevê-lo.")

    # Validate the local app config before touching registry settings.
    previous_mode = None
    if _APP_CONFIG.is_file():
        try:
            app_data = json.loads(_APP_CONFIG.read_text("utf-8"))
            if not isinstance(app_data, dict):
                raise ValueError("unexpected root type")
            previous_mode = app_data.get("deploymentMode")
        except Exception as exc:
            raise RuntimeError("A configuração local do Claude Desktop não é JSON válido; arquivo preservado.") from exc

    user_exists, user_values = _read_values(winreg.HKEY_CURRENT_USER, _POLICY_PATH)
    if not _BACKUP_FILE.exists():
        _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        snapshot = {
            "key_existed": user_exists,
            "values": {name: user_values[name] for name in _POLICY_NAMES if name in user_values},
            "previous_deployment_mode": previous_mode,
        }
        _BACKUP_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")

    key = winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _POLICY_PATH, 0, winreg.KEY_SET_VALUE)
    try:
        values = {
            "inferenceProvider": "gateway",
            "inferenceGatewayBaseUrl": f"http://127.0.0.1:{port}",
            "inferenceGatewayApiKey": "ai-bridge-local",
            "inferenceGatewayAuthScheme": "bearer",
            "inferenceCredentialKind": "static",
            "inferenceModels": json.dumps(models, ensure_ascii=False),
            "modelDiscoveryEnabled": "false",
        }
        for name, value in values.items():
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    finally:
        winreg.CloseKey(key)

    _write_app_mode("3p")
    return {"ok": True, "port": port, "models": len(models), "restart_required": True}


def disconnect() -> dict:
    """Restore prior per-user gateway values and return to the signed-in Claude mode."""
    winreg = _registry()
    snapshot = None
    if _BACKUP_FILE.is_file():
        try:
            snapshot = json.loads(_BACKUP_FILE.read_text("utf-8"))
        except Exception as exc:
            raise RuntimeError("O backup de configuração do Claude Desktop está inválido; nenhuma configuração foi removida.") from exc

    user_exists, current_values = _read_values(winreg.HKEY_CURRENT_USER, _POLICY_PATH)
    if not snapshot and user_exists:
        current_provider = current_values.get("inferenceProvider", {}).get("value")
        current_url = current_values.get("inferenceGatewayBaseUrl", {}).get("value", "")
        current_key = current_values.get("inferenceGatewayApiKey", {}).get("value")
        if current_provider == "gateway" and current_url.startswith("http://127.0.0.1:") and current_key == "ai-bridge-local":
            # Recognizable AI Bridge settings, but missing backup: remove only our own values.
            snapshot = {"values": {}, "previous_deployment_mode": None}
        elif any(name in current_values for name in _POLICY_NAMES):
            raise RuntimeError("Há uma configuração de gateway externa que o AI Bridge não criou. Ela foi preservada para não quebrar sua conexão original.")

    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _POLICY_PATH, 0, winreg.KEY_SET_VALUE)
    except FileNotFoundError:
        key = None
    if key is not None and snapshot is not None:
        try:
            for name in _POLICY_NAMES:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
            for name, item in snapshot.get("values", {}).items():
                if name in _POLICY_NAMES:
                    winreg.SetValueEx(key, name, 0, item["type"], item["value"])
        finally:
            winreg.CloseKey(key)

    # Return to normal signed-in mode without deleting Claude's account/session data.
    if snapshot and snapshot.get("values"):
        _write_app_mode(snapshot.get("previous_deployment_mode") or "3p")
    else:
        _write_app_mode("1p")

    if _BACKUP_FILE.exists():
        _BACKUP_FILE.unlink()
    return {"ok": True, "restart_required": True}


def is_configured(port=None) -> bool:
    try:
        winreg = _registry()
        exists, values = _read_values(winreg.HKEY_CURRENT_USER, _POLICY_PATH)
        if not exists:
            return False
        provider = values.get("inferenceProvider", {}).get("value")
        base_url = values.get("inferenceGatewayBaseUrl", {}).get("value", "")
        return provider == "gateway" and base_url.startswith("http://127.0.0.1:") and (
            port is None or base_url == f"http://127.0.0.1:{port}"
        )
    except Exception:
        return False


def deployment_mode() -> str:
    try:
        data = json.loads(_APP_CONFIG.read_text("utf-8")) if _APP_CONFIG.is_file() else {}
        return data.get("deploymentMode", "1p") if isinstance(data, dict) else "1p"
    except Exception:
        return "unknown"
