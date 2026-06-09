from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status


MAX_DATASET_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_CSV_UPLOAD_BYTES = MAX_DATASET_UPLOAD_BYTES
CSV_UPLOAD_CHUNK_BYTES = 1024 * 1024
DELIMITED_TEXT_UPLOAD_SUFFIXES = {".csv", ".data"}


def validate_upload_filename(filename: str) -> str:
    normalized = filename.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename is required")
    if Path(normalized).name != normalized or "\\" in normalized or "/" in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename must not contain path separators")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename contains control characters")
    return normalized


def validate_upload_content_type(content_type: str | None) -> None:
    # Browsers and proxies do not report dataset MIME types consistently.
    # The stored file path is the source of truth and Codex chooses the reader.
    return


def validate_csv_sample(sample: bytes) -> None:
    if not sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded CSV is empty")
    if b"\x00" in sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded file contains binary null bytes")
    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"uploaded CSV is not valid UTF-8: {exc}") from exc


def is_csv_upload_filename(filename: str) -> bool:
    return Path(filename).suffix.lower() in DELIMITED_TEXT_UPLOAD_SUFFIXES
