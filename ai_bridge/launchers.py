"""Safe launch/restart helpers for installed AI clients."""
import json
import os
import shutil
import subprocess
import sys


def _claude_desktop_processes():
    if sys.platform != "win32":
        return []
    script = r"""
$items = Get-CimInstance Win32_Process -Filter "name='Claude.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.ExecutablePath -like '*\WindowsApps\Claude_*\app\Claude.exe' } |
  Select-Object ProcessId, ExecutablePath
$items | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        parsed = json.loads(result.stdout)
        return parsed if isinstance(parsed, list) else [parsed]
    except Exception:
        return []


def is_running(target_id: str) -> bool:
    if target_id == "claude_desktop":
        return bool(_claude_desktop_processes())
    # Existing Codex/Claude Code sessions are not terminated. A new terminal
    # opens with the new configuration, leaving any active work untouched.
    return False


def _launch_claude_desktop():
    if sys.platform == "win32":
        # Official deep link launches the registered MSIX app and preserves its profile.
        os.startfile("claude://claude.ai/new")
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", "claude://claude.ai/new"])
        return
    raise RuntimeError("A abertura automática do Claude Desktop não é suportada neste sistema.")


def _restart_claude_desktop():
    processes = _claude_desktop_processes()
    if not processes:
        _launch_claude_desktop()
        return {"launched": True, "restarted": False}

    script = r"""
$apps = Get-Process -Name Claude -ErrorAction SilentlyContinue |
  Where-Object { $_.Path -like '*\WindowsApps\Claude_*\app\Claude.exe' -and $_.MainWindowHandle -ne 0 }
foreach ($app in $apps) { [void]$app.CloseMainWindow() }
$deadline = (Get-Date).AddSeconds(10)
do {
  Start-Sleep -Milliseconds 250
  $remaining = Get-Process -Name Claude -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like '*\WindowsApps\Claude_*\app\Claude.exe' -and $_.MainWindowHandle -ne 0 }
} while ($remaining -and (Get-Date) -lt $deadline)
if ($remaining) { exit 23 }
exit 0
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=13, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "O Claude Desktop está aberto e não fechou de forma segura. Salve o trabalho e feche o Claude Desktop; depois clique novamente. O AI Bridge não encerrou processos à força."
        )
    _launch_claude_desktop()
    return {"launched": True, "restarted": True}


def _resolve_cli(command: str):
    found = shutil.which(command)
    if found:
        return found
    if sys.platform == "win32":
        from pathlib import Path
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        if command == "codex":
            candidates = list((local / "OpenAI" / "Codex" / "bin").glob("*/codex.exe"))
        else:
            candidates = list((local / "Claude-Data").glob("claude_*/claude-code/*/*/claude.exe"))
        candidates = [candidate for candidate in candidates if candidate.is_file()]
        if candidates:
            return str(max(candidates, key=lambda item: item.stat().st_mtime))
    return None


def _launch_cli(command: str, title: str):
    executable = _resolve_cli(command)
    if not executable:
        raise RuntimeError(f"{command} não foi encontrado em um caminho conhecido. Nenhuma janela foi aberta.")
    if sys.platform == "win32":
        wt = shutil.which("wt.exe") or shutil.which("wt")
        command_line = f'"{executable}"'
        if wt:
            subprocess.Popen([wt, "new-tab", "--title", title, "cmd.exe", "/k", command_line])
        else:
            subprocess.Popen(["cmd.exe", "/k", command_line])
    else:
        raise RuntimeError(
            f"{command} está instalado, mas a abertura automática de terminal não está configurada neste sistema."
        )
    return {"launched": True, "restarted": False}


def launch_target(target_id: str, restart: bool = False) -> dict:
    if target_id == "claude_desktop":
        if restart:
            return _restart_claude_desktop()
        _launch_claude_desktop()
        return {"launched": True, "restarted": False}
    if target_id == "codex":
        return _launch_cli("codex", "Codex via AI Bridge")
    if target_id == "claude_code":
        return _launch_cli("claude", "Claude Code via AI Bridge")
    raise RuntimeError(f"Aplicativo desconhecido: {target_id}")
