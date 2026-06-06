from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings
from backend.app.services.codex_backend import CodexBackendError, reload_codex_config


DEFAULT_MODEL_DISPLAY_NAME = "Codex"
MODEL_PROFILE_FILENAME = "model_profile.json"
REDACTED_SECRET_VALUE = "***"


def read_model_profile(settings: Settings) -> dict[str, str]:
    profile = _read_profile(settings)
    return {"display_name": _normalize_display_name(profile.get("display_name"))}


def read_model_config(settings: Settings) -> dict[str, Any]:
    profile = read_model_profile(settings)
    auth_path, config_path = _codex_paths(settings)
    auth_payload = _read_auth_payload(auth_path)
    return {
        **profile,
        "auth_json": "",
        "config_toml": _redact_config_toml(_read_text(config_path)),
        "auth_path": auth_path.name,
        "config_path": config_path.name,
        "auth_configured": bool(_find_primary_auth_secret(auth_payload)),
        "auth_key_preview": _auth_key_preview(auth_payload),
    }


def save_model_config(
    settings: Settings,
    *,
    display_name: str,
    config_toml: str,
    api_key: str = "",
    auth_json: str | None = None,
) -> dict[str, Any]:
    normalized_display_name = _normalize_display_name(display_name)
    auth_path, config_path = _codex_paths(settings)
    normalized_config_toml = _restore_redacted_toml_values(config_toml, _read_text(config_path))
    _validate_toml_if_available(normalized_config_toml)

    auth_path.parent.mkdir(parents=True, exist_ok=True)
    if str(api_key or "").strip():
        _write_auth_api_key(auth_path, str(api_key).strip())
    _atomic_write_text(config_path, normalized_config_toml)
    _write_profile(settings, {"display_name": normalized_display_name})

    reload_result = _reload_codex_backend(settings)
    return {
        **read_model_config(settings),
        "reload": reload_result,
    }


def _codex_paths(settings: Settings) -> tuple[Path, Path]:
    config_dir = Path(settings.codex_config_dir).expanduser()
    return config_dir / "auth.json", config_dir / "config.toml"


def _profile_path(settings: Settings) -> Path:
    return Path(settings.storage_dir).parent / MODEL_PROFILE_FILENAME


def _read_profile(settings: Settings) -> dict[str, Any]:
    path = _profile_path(settings)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_profile(settings: Settings, payload: dict[str, str]) -> None:
    path = _profile_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding="utf-8")
    temp_path.replace(path)


def _normalize_display_name(value: object) -> str:
    name = str(value or "").strip()
    if not name:
        return DEFAULT_MODEL_DISPLAY_NAME
    return name[:48]


def _normalize_auth_json(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"auth.json 不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列。") from exc
    if not isinstance(payload, dict):
        raise ValueError("auth.json 顶层必须是 JSON 对象。")
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _read_auth_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _find_primary_auth_secret(payload: dict[str, Any]) -> str:
    preferred = payload.get("OPENAI_API_KEY")
    if isinstance(preferred, str) and preferred.strip():
        return preferred.strip()
    for key, value in payload.items():
        if _is_secret_key(str(key)) and isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _auth_key_preview(payload: dict[str, Any]) -> str:
    secret = _find_primary_auth_secret(payload)
    if not secret:
        return "未配置"
    suffix = secret[-4:] if len(secret) >= 4 else secret
    return f"已配置（末尾 {suffix}）"


def _write_auth_api_key(path: Path, api_key: str) -> None:
    if api_key == REDACTED_SECRET_VALUE:
        raise ValueError("新 API Key 不能使用脱敏占位符。")
    payload = _read_auth_payload(path)
    payload["OPENAI_API_KEY"] = api_key
    _atomic_write_text(path, _normalize_auth_json(json.dumps(payload, ensure_ascii=False)))


def _is_secret_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    exact_secret_names = {
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "id_token",
        "bearer_token",
        "authorization",
        "secret",
        "password",
        "credential",
        "credentials",
    }
    if normalized in exact_secret_names:
        return True
    secret_suffixes = (
        "_api_key",
        "_access_token",
        "_refresh_token",
        "_id_token",
        "_bearer_token",
        "_secret",
        "_password",
        "_credential",
        "_credentials",
    )
    return normalized.endswith(secret_suffixes)


def _toml_section_name(line: str) -> str | None:
    stripped = line.strip()
    match = re.match(r"^\[{1,2}\s*([^\]]+?)\s*\]{1,2}(?:\s*#.*)?$", stripped)
    if not match:
        return None
    return match.group(1).strip()


def _split_toml_assignment(line: str) -> tuple[str, str, str] | None:
    if line.lstrip().startswith("#"):
        return None
    if "=" not in line:
        return None
    left, right = line.split("=", 1)
    key = left.strip().strip('"').strip("'")
    if not key:
        return None
    return f"{left}=", key, right


def _redact_config_toml(value: str) -> str:
    lines = []
    for line in str(value or "").splitlines(keepends=True):
        assignment = _split_toml_assignment(line)
        if assignment is None:
            lines.append(line)
            continue
        prefix, key, _right = assignment
        if _is_secret_key(key):
            newline = "\n" if line.endswith("\n") else ""
            lines.append(f'{prefix} "{REDACTED_SECRET_VALUE}"{newline}')
            continue
        lines.append(line)
    return "".join(lines)


def _toml_secret_values_by_path(value: str) -> dict[tuple[str, str], str]:
    section = ""
    values: dict[tuple[str, str], str] = {}
    for line in str(value or "").splitlines(keepends=True):
        section_name = _toml_section_name(line)
        if section_name is not None:
            section = section_name
            continue
        assignment = _split_toml_assignment(line)
        if assignment is None:
            continue
        _prefix, key, right = assignment
        if _is_secret_key(key):
            values[(section, key)] = right
    return values


def _restore_redacted_toml_values(incoming: str, current: str) -> str:
    current_values = _toml_secret_values_by_path(current)
    section = ""
    lines = []
    redacted_values = {f'"{REDACTED_SECRET_VALUE}"', f"'{REDACTED_SECRET_VALUE}'", REDACTED_SECRET_VALUE}
    for line in str(incoming or "").splitlines(keepends=True):
        section_name = _toml_section_name(line)
        if section_name is not None:
            section = section_name
            lines.append(line)
            continue
        assignment = _split_toml_assignment(line)
        if assignment is None:
            lines.append(line)
            continue
        prefix, key, right = assignment
        if _is_secret_key(key) and right.strip() in redacted_values and (section, key) in current_values:
            lines.append(f"{prefix}{current_values[(section, key)]}")
            continue
        lines.append(line)
    return "".join(lines)


def _validate_toml_if_available(value: str) -> None:
    text = str(value or "")
    if not text.strip():
        return
    try:
        import tomllib
    except ModuleNotFoundError:
        return
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"config.toml 不是合法 TOML：{exc}") from exc


def _reload_codex_backend(settings: Settings) -> dict[str, Any]:
    try:
        return reload_codex_config(settings)
    except CodexBackendError as exc:
        return {
            "reloaded": False,
            "detail": str(exc),
        }
