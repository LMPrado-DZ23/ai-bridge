"""Multi-provider catalog regression tests."""
import json

from ai_bridge import codex, config


def test_codex_catalog_includes_every_model_from_multiple_providers(tmp_path, monkeypatch):
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    catalog_path = codex_dir / "ai-bridge-models.json"
    monkeypatch.setattr(codex, "CODEX_DIR", codex_dir)
    monkeypatch.setattr(codex, "CODEX_CATALOG_FILE", catalog_path)
    monkeypatch.setattr(config, "all_picker_models", lambda: [
        {"value": "DeepSeek/deepseek-flash", "label": "DeepSeek Flash · DeepSeek"},
        {"value": "DeepSeek/deepseek-v4-pro", "label": "DeepSeek V4 Pro · DeepSeek"},
        {"value": "OpenRouter/anthropic/claude-sonnet", "label": "Claude Sonnet · OpenRouter"},
        {"value": "Gemini/gemini-2.5-pro", "label": "Gemini 2.5 Pro · Gemini"},
    ])

    codex._write_catalog_file()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert [model["slug"] for model in catalog["models"]] == [
        "DeepSeek/deepseek-flash",
        "DeepSeek/deepseek-v4-pro",
        "OpenRouter/anthropic/claude-sonnet",
        "Gemini/gemini-2.5-pro",
    ]
    assert len({model["slug"] for model in catalog["models"]}) == 4
    assert all(model["visibility"] == "list" for model in catalog["models"])
    assert all(model["supported_in_api"] for model in catalog["models"])


def test_claude_gateway_catalog_includes_models_from_multiple_providers(monkeypatch):
    monkeypatch.setattr(config, "get_providers", lambda: [
        {"name": "DeepSeek", "models": [
            {"id": "deepseek-flash", "label": "DeepSeek Flash"},
            {"id": "deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
        ]},
        {"name": "OpenRouter", "models": [
            {"id": "anthropic/claude-sonnet", "label": "Claude Sonnet"},
        ]},
    ])
    monkeypatch.setattr(config, "load", lambda: {
        "active_model": "DeepSeek/deepseek-v4-pro"
    })

    models = config.claude_desktop_models()

    assert models == [
        {"name": "claude-sonnet-5", "labelOverride": "DeepSeek V4 Pro · DeepSeek (AI Bridge)"},
        {"name": "claude-sonnet-5-2", "labelOverride": "DeepSeek Flash · DeepSeek (AI Bridge)"},
        {"name": "claude-sonnet-5-3", "labelOverride": "Claude Sonnet · OpenRouter (AI Bridge)"},
    ]
    assert config.get_model_id("claude-sonnet-5-3") == "anthropic/claude-sonnet"

def test_codex_catalog_mixes_oauth_and_api_key_models(tmp_path, monkeypatch):
    """O catálogo do Codex é único: mistura modelos OAuth e de API key."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    catalog_path = codex_dir / "ai-bridge-models.json"
    monkeypatch.setattr(codex, "CODEX_DIR", codex_dir)
    monkeypatch.setattr(codex, "CODEX_CATALOG_FILE", catalog_path)
    monkeypatch.setattr(config, "all_picker_models", lambda: [
        {"value": "Codex (OAuth)/gpt-6-luna", "label": "GPT-6 Luna · Codex (OAuth)"},
        {"value": "DeepSeek/deepseek-v4-pro", "label": "DeepSeek V4 Pro · DeepSeek"},
        {"value": "Claude Code (OAuth)/claude-sonnet-5", "label": "Claude Sonnet 5 · Claude Code (OAuth)"},
    ])

    codex._write_catalog_file()
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))

    assert [model["slug"] for model in catalog["models"]] == [
        "Codex (OAuth)/gpt-6-luna",
        "DeepSeek/deepseek-v4-pro",
        "Claude Code (OAuth)/claude-sonnet-5",
    ]
    assert all(model["provider"] == "ai_bridge" for model in catalog["models"])

def test_codex_connect_writes_unified_catalog_and_reverts(tmp_path, monkeypatch):
    """Conectar o Codex grava UMA lista (OAuth + API key) e desconectar restaura tudo."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config_path = codex_dir / "config.toml"
    catalog_path = codex_dir / "ai-bridge-models.json"
    state_path = codex_dir / ".ai-bridge-state.json"
    config_path.write_text('model = "gpt-5.5"\nmodel_provider = "openai"\n', encoding="utf-8")

    monkeypatch.setattr(codex, "CODEX_DIR", codex_dir)
    monkeypatch.setattr(codex, "CODEX_CONFIG", config_path)
    monkeypatch.setattr(codex, "CODEX_CATALOG_FILE", catalog_path)
    monkeypatch.setattr(codex, "_STATE_FILE", state_path)
    monkeypatch.setattr(config, "all_picker_models", lambda: [
        {"value": "Codex (OAuth)/gpt-6-luna", "label": "GPT-6 Luna · Codex (OAuth)"},
        {"value": "DeepSeek/deepseek-v4-pro", "label": "DeepSeek V4 Pro · DeepSeek"},
    ])
    monkeypatch.setattr(config, "get_active_model", lambda: "Codex (OAuth)/gpt-6-luna")

    codex.connect(38771)

    text = config_path.read_text(encoding="utf-8")
    assert 'model_provider = "ai_bridge"' in text
    assert 'model_catalog_json = ' in text
    assert 'ai-bridge-models.json' in text
    assert '[model_providers.ai_bridge]' in text
    assert 'wire_api = "responses"' in text
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert [m["slug"] for m in catalog["models"]] == [
        "Codex (OAuth)/gpt-6-luna", "DeepSeek/deepseek-v4-pro",
    ]

    codex.disconnect()

    restored = config_path.read_text(encoding="utf-8")
    assert 'model = "gpt-5.5"' in restored
    assert 'model_provider = "openai"' in restored
    assert 'model_provider = "ai_bridge"' not in restored
    assert 'model_catalog_json' not in restored
    assert not state_path.exists()
