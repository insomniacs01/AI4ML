from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from backend.app.models.task import TaskCodeArtifactEntry
from backend.app.services.task_code_artifact_descriptors import (
    GROUP_ORDER,
    describe_artifact,
    detect_artifact_language,
    is_editable_artifact,
)
from backend.app.services.task_code_versions import VERSION_MANIFEST_NAME
from backend.app.services.task_output_resolution import recent_node_dirs


def collect_workspace_entries(run_output_dir: Path) -> list[TaskCodeArtifactEntry]:
    entries: list[TaskCodeArtifactEntry] = []
    for path in iter_workspace_candidate_files(run_output_dir):
        if not path.is_file():
            continue
        if path.name == VERSION_MANIFEST_NAME:
            continue
        if "best_run" in path.parts:
            continue
        entry = artifact_entry_from_path(run_output_dir, path)
        if entry is not None:
            entries.append(entry)

    entries.sort(key=entry_sort_key)
    return entries


def artifact_entry_from_path(run_output_dir: Path, path: Path) -> TaskCodeArtifactEntry | None:
    language = detect_artifact_language(path)
    if language is None:
        return None

    relative_path = path.relative_to(run_output_dir).as_posix()
    descriptor = describe_artifact(relative_path, path.name)
    stats = path.stat()

    return TaskCodeArtifactEntry(
        path=relative_path,
        name=path.name,
        display_name=descriptor.display_name,
        purpose=descriptor.purpose,
        editing_guidance=descriptor.editing_guidance,
        category=descriptor.category,
        group=descriptor.group,
        artifact_kind=descriptor.artifact_kind,
        stage=descriptor.stage,
        node=extract_node_name(relative_path),
        is_core=descriptor.is_core,
        recommended_order=descriptor.sort_priority,
        language=language,
        size_bytes=stats.st_size,
        editable=is_editable_artifact(descriptor, language),
        updated_at=datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc),
    )


def resolve_artifact_path(run_output_dir: Path, artifact_path: str) -> Path:
    candidate = artifact_path.strip()
    if not candidate:
        raise FileNotFoundError("Artifact path is required.")

    normalized_relative = Path(candidate.replace("\\", "/"))
    if normalized_relative.is_absolute():
        raise PermissionError("Artifact path must be relative to the latest run output directory.")

    run_root = run_output_dir.resolve()
    resolved_path = (run_root / normalized_relative).resolve()

    if run_root not in resolved_path.parents and resolved_path != run_root:
        raise PermissionError("Artifact path escapes the latest run output directory.")
    if "best_run" in resolved_path.parts:
        raise PermissionError("best_run shadow copies are not editable from the workspace.")
    if not resolved_path.exists() or not resolved_path.is_file():
        raise FileNotFoundError(f"Artifact not found: {artifact_path}")

    return resolved_path


def find_default_rerun_path(run_output_dir: Path) -> str | None:
    candidates = [
        path
        for path in [
            run_output_dir / "generated_code.py",
            *[node_dir / "generated_code.py" for node_dir in recent_node_dirs(run_output_dir)],
        ]
        if path.is_file() and "best_run" not in path.parts
    ]
    candidates = sorted(candidates, key=lambda item: item.stat().st_mtime, reverse=True)
    if not candidates:
        return None
    return candidates[0].relative_to(run_output_dir).as_posix()


def iter_workspace_candidate_files(run_output_dir: Path) -> list[Path]:
    roots = [
        run_output_dir,
        run_output_dir / "output",
        run_output_dir / "output" / "code",
        run_output_dir / "output" / "logs",
        run_output_dir / "input",
        run_output_dir / "state",
    ]
    node_dirs = recent_node_dirs(run_output_dir)
    roots.extend(node_dirs)
    for node_dir in node_dirs:
        roots.extend([node_dir / "states", node_dir / "output", node_dir / "logs"])

    candidates: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.is_file() or path in seen:
                continue
            seen.add(path)
            candidates.append(path)
    return sorted(candidates)


def entry_sort_key(entry: TaskCodeArtifactEntry) -> tuple[int, int, int, int, str]:
    return (
        0 if entry.is_core else 1,
        GROUP_ORDER.get(entry.group, 999),
        entry.recommended_order,
        extract_node_order(entry.path),
        entry.path.lower(),
    )


def extract_node_name(relative_path: str) -> str | None:
    for part in relative_path.split("/"):
        if part.startswith("node_"):
            return part
    return None


def extract_node_order(relative_path: str) -> int:
    for part in relative_path.split("/"):
        if not part.startswith("node_"):
            continue
        try:
            return int(part.removeprefix("node_"))
        except ValueError:
            return 999
    return -1
