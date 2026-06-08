from __future__ import annotations

from backend.app.services.model_config_secrets import (
    is_secret_key,
    redact_config_toml,
    restore_redacted_toml_values,
)


def test_is_secret_key_matches_exact_and_suffix_names() -> None:
    assert is_secret_key("api-key") is True
    assert is_secret_key("provider_access_token") is True
    assert is_secret_key("model_auto_compact_token_limit") is False


def test_redact_config_toml_preserves_comments_and_non_secret_values() -> None:
    redacted = redact_config_toml(
        '# api_key = "example"\n'
        'model = "gpt-5"\n'
        '[providers.openai]\n'
        'api_key = "live-secret"\n'
    )

    assert '# api_key = "example"' in redacted
    assert 'model = "gpt-5"' in redacted
    assert 'api_key = "***"' in redacted
    assert "live-secret" not in redacted


def test_restore_redacted_toml_values_uses_matching_section_and_key() -> None:
    current = (
        '[providers.openai]\n'
        'api_key = "openai-secret"\n'
        '[providers.azure]\n'
        'api_key = "azure-secret"\n'
    )
    incoming = (
        '[providers.openai]\n'
        'api_key = "***"\n'
        '[providers.azure]\n'
        'api_key = "new-azure-secret"\n'
    )

    restored = restore_redacted_toml_values(incoming, current)

    assert 'api_key = "openai-secret"' in restored
    assert 'api_key = "new-azure-secret"' in restored
    assert 'api_key = "azure-secret"' not in restored
