from __future__ import annotations

import re


REDACTED_SECRET_VALUE = "***"


def is_secret_key(key: str) -> bool:
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


def redact_config_toml(value: str) -> str:
    lines = []
    for line in str(value or "").splitlines(keepends=True):
        assignment = _split_toml_assignment(line)
        if assignment is None:
            lines.append(line)
            continue
        prefix, key, _right = assignment
        if is_secret_key(key):
            newline = "\n" if line.endswith("\n") else ""
            lines.append(f'{prefix} "{REDACTED_SECRET_VALUE}"{newline}')
            continue
        lines.append(line)
    return "".join(lines)


def restore_redacted_toml_values(incoming: str, current: str) -> str:
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
        if is_secret_key(key) and right.strip() in redacted_values and (section, key) in current_values:
            lines.append(f"{prefix}{current_values[(section, key)]}")
            continue
        lines.append(line)
    return "".join(lines)


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
        if is_secret_key(key):
            values[(section, key)] = right
    return values
