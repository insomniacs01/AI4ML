from __future__ import annotations

from pathlib import Path


def get_project_env_files(repo_root: Path) -> tuple[Path, ...]:
    return (
        repo_root / ".env",
        repo_root / ".env.local",
        repo_root / "backend" / ".env",
        repo_root / "backend" / ".env.local",
        repo_root / "frontend" / ".env",
        repo_root / "frontend" / ".env.local",
    )


def parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        values[key.strip()] = raw_value.strip().strip("\"'")
    return values


def load_frontend_env(repo_root: Path) -> dict[str, str]:
    frontend_dir = repo_root / "frontend"
    values: dict[str, str] = {}
    for filename in (".env", ".env.local"):
        values.update(parse_env_file(frontend_dir / filename))
    return values
