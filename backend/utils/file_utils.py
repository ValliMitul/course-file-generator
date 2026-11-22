"""Filesystem helpers: filename sanitising and streamed uploads to scratch space."""
import os
import re
import shutil
from pathlib import Path

from fastapi import UploadFile

from backend import config
from backend.errors import AppError

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def sanitize_filename(name: str | None) -> str:
    """Return a display-safe filename (no directories, control chars or reserved chars)."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    name = _CONTROL.sub("", name)
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if len(name) > 150:
        stem, ext = os.path.splitext(name)
        name = stem[: 150 - len(ext)] + ext
    return name


def sanitize_for_output(text: str) -> str:
    """Make arbitrary text (e.g. a course code) safe for use in an output filename."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")


def save_upload(upload: UploadFile, dest: Path, max_bytes: int = config.MAX_UPLOAD_BYTES) -> int:
    """Stream an upload to *dest* enforcing the size limit. Returns the byte size."""
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise AppError(413, f"File is too large. The limit is {max_bytes // (1024 * 1024)} MB.")
                out.write(chunk)
    except Exception:
        dest.unlink(missing_ok=True)
        raise
    if size == 0:
        dest.unlink(missing_ok=True)
        raise AppError(400, "The uploaded file is empty.")
    return size


def remove_quietly(*paths: Path | None) -> None:
    for p in paths:
        if p is None:
            continue
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def remove_dir_quietly(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
