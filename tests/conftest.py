"""Global test isolation: never touch the user's real AI Bridge config or keyring."""
import pytest

from ai_bridge import config, eventlog


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    config_dir = tmp_path / '.ai-bridge'
    monkeypatch.setattr(config, 'CONFIG_DIR', config_dir)
    monkeypatch.setattr(config, 'CONFIG_FILE', config_dir / 'config.json')
    # Keys live in the OS keyring; tests never read or write it.
    monkeypatch.setattr(config, '_set_key', lambda *args, **kwargs: None)
    monkeypatch.setattr(config, '_delete_key', lambda *args, **kwargs: None)
    monkeypatch.setattr(config, '_get_key', lambda *args, **kwargs: '')
    # The proxy appends request events; keep them out of the real user log.
    monkeypatch.setattr(eventlog, 'LOG_DIR', tmp_path / 'logs')
    yield
