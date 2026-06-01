from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskCodeArtifactVersionRecord

VERSION_MANIFEST_NAME = ".ai4ml_code_workspace_versions.json"
logger = logging.getLogger(__name__)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_version_history(run_output_dir: Path, *, relative_path: str) -> list[TaskCodeArtifactVersionRecord]:
    return [
        record
        for record in read_all_version_records(run_output_dir)
        if record.path == relative_path
    ]


def append_version_record(
    run_output_dir: Path,
    *,
    relative_path: str,
    size_bytes: int,
    previous_sha256: str,
    sha256: str,
) -> TaskCodeArtifactVersionRecord:
    now = datetime.now(timezone.utc)
    version = TaskCodeArtifactVersionRecord(
        version_id=f"{now.strftime('%Y%m%dT%H%M%SZ')}-{sha256[:12]}",
        path=relative_path,
        saved_at=now,
        size_bytes=size_bytes,
        previous_sha256=previous_sha256,
        sha256=sha256,
    )
    records = read_all_version_records(run_output_dir)
    records.append(version)
    write_version_records(run_output_dir, records)
    return version


def read_all_version_records(run_output_dir: Path) -> list[TaskCodeArtifactVersionRecord]:
    manifest = version_manifest_path(run_output_dir)
    if not manifest.exists():
        return []
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read code artifact version manifest %s: %s", manifest, exc)
        return []
    rows = payload.get("versions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    records: list[TaskCodeArtifactVersionRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            records.append(TaskCodeArtifactVersionRecord.model_validate(row))
        except Exception as exc:
            logger.debug("Skipping invalid code artifact version row in %s: %s", manifest, exc)
            continue
    return records


def write_version_records(run_output_dir: Path, records: list[TaskCodeArtifactVersionRecord]) -> None:
    manifest = version_manifest_path(run_output_dir)
    manifest.write_text(
        json.dumps({"versions": [record.model_dump(mode="json") for record in records]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def version_manifest_path(run_output_dir: Path) -> Path:
    return run_output_dir / VERSION_MANIFEST_NAME
