"""
Claude Desktop integration for AI Bridge.
Writes ANTHROPIC_BASE_URL to the app config and Windows user env.
"""
import json
import os
import shutil
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

def _resolve_cfg_dir() -> Path:
    """Resolve the config directory used by the installed Claude Desktop build.

    The Microsoft Store/MSIX build can use a custom Electron user-data directory
    under %LOCALAPPDATA%\\Claude-Data\\claude_<package-family-suffix>, rather
    than the legacy %APPDATA%\\Claude path.
    """
    if sys.platform == 'win32':
        appdata = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        legacy = appdata / 'Claude'
        data_root = local / 'Claude-Data'
        data_dirs = sorted(
            (p for p in data_root.glob('claude_*') if p.is_dir()),
            key=lambda p: (p / 'claude_desktop_config.json').exists(),
            reverse=True,
        )
        # Prefer an existing config, never create a second empty config beside it.
        for candidate in data_dirs:
            if (candidate / 'claude_desktop_config.json').is_file():
                return candidate
        if legacy.joinpath('claude_desktop_config.json').is_file():
            return legacy
        # If the Store app is installed but has not created its config yet,
        # derive its user-data folder from the MSIX package family suffix.
        package_root = local / 'Packages'
        for package_dir in sorted(package_root.glob('Claude_*')):
            suffix = package_dir.name.removeprefix('Claude_')
            candidate = data_root / f'claude_{suffix}'
            if candidate.exists() or package_dir.is_dir():
                return candidate
        if data_dirs:
            return data_dirs[0]
        return legacy
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Application Support' / 'Claude'
    return Path.home() / '.config' / 'Claude'


_CFG_DIR = _resolve_cfg_dir()
_CFG_FILE = _CFG_DIR / 'claude_desktop_config.json'
_BRIDGE_KEY = '_ai_bridge'


@dataclass
class ClaudeDesktopState:
    installed: bool
    connected: bool
    port: Optional[int]


def _is_installed() -> bool:
    if _CFG_DIR.exists():
        return True
    if sys.platform == 'win32':
        local = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local'))
        # MSIX installs create a package data folder even when the old
        # %APPDATA%\\Claude directory is absent.
        if any((local / 'Packages').glob('Claude_*')):
            return True
        if any((local / 'Claude-Data').glob('claude_*')):
            return True
        for executable in (
            local / 'Programs' / 'Claude' / 'Claude.exe',
            local / 'Claude' / 'Claude.exe',
            Path(os.environ.get('ProgramFiles', 'C:\\\\Program Files')) / 'Claude' / 'Claude.exe',
        ):
            if executable.is_file():
                return True
        windows_apps = Path(os.environ.get('ProgramFiles', 'C:\\\\Program Files')) / 'WindowsApps'
        if windows_apps.exists():
            try:
                if any(windows_apps.glob('Claude_*/app/Claude.exe')):
                    return True
            except (OSError, PermissionError):
                pass
    return False


def _load() -> dict:
    if not _CFG_FILE.exists():
        return {}
    try:
        return json.loads(_CFG_FILE.read_text('utf-8'))
    except Exception:
        return {}


def _write(data: dict):
    _CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _CFG_DIR / f'.aib-{os.getpid()}.tmp'
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), 'utf-8')
    tmp.replace(_CFG_FILE)


def _set_win_env(key: str, value: str):
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0,
                            winreg.KEY_SET_VALUE) as reg:
            winreg.SetValueEx(reg, key, 0, winreg.REG_EXPAND_SZ, value)
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, 'Environment', 2, 5000, None)
    except Exception:
        pass


def _del_win_env(key: str):
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment', 0,
                            winreg.KEY_SET_VALUE) as reg:
            try:
                winreg.DeleteValue(reg, key)
            except FileNotFoundError:
                pass
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x001A, 0, 'Environment', 2, 5000, None)
    except Exception:
        pass


def _set_mac_env(key: str, value: str):
    if sys.platform != 'darwin':
        return
    try:
        import subprocess
        subprocess.run(['launchctl', 'setenv', key, value], timeout=5)
    except Exception:
        pass


def _del_mac_env(key: str):
    if sys.platform != 'darwin':
        return
    try:
        import subprocess
        subprocess.run(['launchctl', 'unsetenv', key], timeout=5)
    except Exception:
        pass


def connect(port: int):
    """Route Claude Desktop API calls through AI Bridge, preserving user config."""
    if _CFG_FILE.exists():
        # Never replace a malformed file with a partial config. Back up the
        # original before the first AI Bridge mutation.
        try:
            json.loads(_CFG_FILE.read_text('utf-8'))
        except Exception as exc:
            raise RuntimeError(
                f'Configuração do Claude Desktop inválida; arquivo preservado: {_CFG_FILE.name}'
            ) from exc

    data = _load()
    if _CFG_FILE.exists() and _BRIDGE_KEY not in data:
        stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = _CFG_FILE.with_name(f'{_CFG_FILE.stem}.ai-bridge-backup-{stamp}{_CFG_FILE.suffix}')
        counter = 1
        while backup.exists():
            backup = _CFG_FILE.with_name(
                f'{_CFG_FILE.stem}.ai-bridge-backup-{stamp}-{counter}{_CFG_FILE.suffix}'
            )
            counter += 1
        shutil.copy2(_CFG_FILE, backup)

    data[_BRIDGE_KEY] = {'port': port}
    _write(data)

    url = f'http://127.0.0.1:{port}'
    _set_win_env('ANTHROPIC_BASE_URL', url)
    _set_mac_env('ANTHROPIC_BASE_URL', url)


def disconnect():
    """Remove AI Bridge config from Claude Desktop."""
    data = _load()
    data.pop(_BRIDGE_KEY, None)
    if data:
        _write(data)

    _del_win_env('ANTHROPIC_BASE_URL')
    _del_mac_env('ANTHROPIC_BASE_URL')


def state() -> ClaudeDesktopState:
    if not _is_installed():
        return ClaudeDesktopState(installed=False, connected=False, port=None)
    bridge = _load().get(_BRIDGE_KEY)
    if bridge:
        return ClaudeDesktopState(installed=True, connected=True, port=bridge.get('port'))
    return ClaudeDesktopState(installed=True, connected=False, port=None)


def is_connected() -> bool:
    return state().connected

[executed on device: DZ23_PRADO (23cb9a21-fa9a-41c8-9057-7c779b224cee)]