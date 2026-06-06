from __future__ import annotations

import json

from backend.app.core.config import Settings
from backend.app.services import model_config


def make_settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        storage_dir=tmp_path / "storage" / "tasks",
        codex_config_dir=tmp_path / "codex",
    )


def write_codex_config(settings: Settings, *, api_key: str = "sk-secret-1234", config_toml: str = "") -> None:
    auth_path = settings.codex_config_dir / "auth.json"
    config_path = settings.codex_config_dir / "config.toml"
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps({"OPENAI_API_KEY": api_key, "OTHER_FIELD": "kept"}), encoding="utf-8")
    config_path.write_text(config_toml, encoding="utf-8")


def test_read_model_config_redacts_auth_and_secret_toml_values(tmp_path) -> None:
    settings = make_settings(tmp_path)
    write_codex_config(
        settings,
        api_key="sk-live-secret-1234",
        config_toml=(
            '# api_key = "example-only"\n'
            'model = "gpt-5"\n'
            'api_key = "toml-secret"\n'
            'model_auto_compact_token_limit = 900000\n'
        ),
    )

    result = model_config.read_model_config(settings)

    assert result["auth_json"] == ""
    assert result["auth_path"] == "auth.json"
    assert result["config_path"] == "config.toml"
    assert result["auth_configured"] is True
    assert result["auth_key_preview"] == "已配置（末尾 1234）"
    assert "sk-live-secret" not in str(result)
    assert 'api_key = "***"' in result["config_toml"]
    assert '# api_key = "example-only"' in result["config_toml"]
    assert "toml-secret" not in result["config_toml"]
    assert "model_auto_compact_token_limit = 900000" in result["config_toml"]


def test_save_model_config_preserves_existing_auth_and_redacted_toml_values(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    write_codex_config(
        settings,
        api_key="sk-existing-5678",
        config_toml='model = "gpt-5"\napi_key = "toml-secret"\n',
    )
    monkeypatch.setattr(model_config, "reload_codex_config", lambda _settings: {"reloaded": True})

    current = model_config.read_model_config(settings)
    edited_toml = current["config_toml"].replace('model = "gpt-5"', 'model = "gpt-5.1"')
    result = model_config.save_model_config(
        settings,
        display_name="AIOUR",
        config_toml=edited_toml,
        api_key="",
    )

    auth_payload = json.loads((settings.codex_config_dir / "auth.json").read_text(encoding="utf-8"))
    raw_toml = (settings.codex_config_dir / "config.toml").read_text(encoding="utf-8")
    assert auth_payload["OPENAI_API_KEY"] == "sk-existing-5678"
    assert auth_payload["OTHER_FIELD"] == "kept"
    assert 'model = "gpt-5.1"' in raw_toml
    assert 'api_key = "toml-secret"' in raw_toml
    assert result["auth_key_preview"] == "已配置（末尾 5678）"
    assert "sk-existing" not in str(result)


def test_save_model_config_replaces_auth_only_when_new_key_is_provided(tmp_path, monkeypatch) -> None:
    settings = make_settings(tmp_path)
    write_codex_config(settings, api_key="sk-old-0000", config_toml='model = "gpt-5"\n')
    monkeypatch.setattr(model_config, "reload_codex_config", lambda _settings: {"reloaded": True})

    model_config.save_model_config(
        settings,
        display_name="AIOUR",
        config_toml='model = "gpt-5"\n',
        api_key="sk-new-9999",
    )

    auth_payload = json.loads((settings.codex_config_dir / "auth.json").read_text(encoding="utf-8"))
    assert auth_payload["OPENAI_API_KEY"] == "sk-new-9999"
    assert auth_payload["OTHER_FIELD"] == "kept"
