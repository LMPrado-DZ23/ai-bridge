"""Regression tests for launching the actual desktop clients, not their CLIs."""
from unittest.mock import Mock

from ai_bridge import launchers


def test_launch_codex_uses_installed_desktop_app(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(launchers.sys, "platform", "win32")
    monkeypatch.setattr(launchers.subprocess, "Popen", popen)

    launchers.launch_target("codex")

    args = popen.call_args.args[0]
    assert args[0] == "explorer.exe"
    assert args[1] == r"shell:AppsFolder\OpenAI.Codex_2p2nqsd0c76g0!App"


def test_launch_claude_desktop_uses_installed_msix_app(monkeypatch):
    popen = Mock()
    monkeypatch.setattr(launchers.sys, "platform", "win32")
    monkeypatch.setattr(launchers.subprocess, "Popen", popen)

    launchers.launch_target("claude_desktop")

    args = popen.call_args.args[0]
    assert args[0] == "explorer.exe"
    assert args[1] == r"shell:AppsFolder\Claude_pzs8sxrjxfjjc!Claude"


def test_codex_target_no_longer_launches_cli(monkeypatch):
    desktop = Mock()
    cli = Mock()
    monkeypatch.setattr(launchers, "_launch_codex_desktop", desktop)
    monkeypatch.setattr(launchers, "_launch_cli", cli)

    result = launchers.launch_target("codex")

    assert result["launched"] is True
    desktop.assert_called_once_with()
    cli.assert_not_called()
