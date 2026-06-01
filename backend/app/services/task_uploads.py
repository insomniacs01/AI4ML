from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status


MAX_CSV_UPLOAD_BYTES = 100 * 1024 * 1024
CSV_UPLOAD_CHUNK_BYTES = 1024 * 1024
ALLOWED_CSV_CONTENT_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
    "application/octet-stream",
}


def validate_upload_filename(filename: str) -> str:
    normalized = filename.strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename is required")
    if Path(normalized).name != normalized or "\\" in normalized or "/" in normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename must not contain path separators")
    if any(ord(char) < 32 for char in normalized):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="dataset filename contains control characters")
    if Path(normalized).suffix.lower() != ".csv":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="only CSV uploads are supported")
    return normalized


def validate_upload_content_type(content_type: str | None) -> None:
    if not content_type:
        return
    normalized = content_type.split(";")[0].strip().lower()
    if normalized not in ALLOWED_CSV_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"unsupported CSV content type: {content_type}",
        )


def validate_csv_sample(sample: bytes) -> None:
    if not sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded CSV is empty")
    if b"\x00" in sample:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="uploaded file contains binary null bytes")
    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"uploaded CSV is not valid UTF-8: {exc}") from exc
