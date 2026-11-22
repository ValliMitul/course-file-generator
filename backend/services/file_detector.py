"""Detect and validate uploaded file types (extension, MIME type, content signature)."""
import logging
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from backend.errors import AppError

log = logging.getLogger("cfg.detector")

_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


@dataclass(frozen=True)
class FileKind:
    ext: str
    category: str   # pdf | word | excel | ppt | txt
    label: str      # shown to users, e.g. DOCX
    mime: str       # canonical MIME type
    extra_mimes: tuple[str, ...] = ()


KINDS: dict[str, FileKind] = {k.ext: k for k in [
    FileKind(".pdf", "pdf", "PDF", "application/pdf", ("application/x-pdf",)),
    FileKind(".doc", "word", "DOC", "application/msword"),
    FileKind(".docx", "word", "DOCX",
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    FileKind(".xls", "excel", "XLS", "application/vnd.ms-excel",
             ("application/msexcel", "application/x-msexcel")),
    FileKind(".xlsx", "excel", "XLSX",
             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    FileKind(".ppt", "ppt", "PPT", "application/vnd.ms-powerpoint",
             ("application/mspowerpoint",)),
    FileKind(".pptx", "ppt", "PPTX",
             "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    FileKind(".txt", "txt", "TXT", "text/plain"),
]}

CATEGORY_LABELS = {"pdf": "PDF", "word": "Word", "excel": "Excel", "ppt": "PowerPoint", "txt": "text"}

# Browsers/OSes often send these for anything; they carry no information, so accept them.
_GENERIC_MIMES = {"", "application/octet-stream", "binary/octet-stream"}

_OOXML_MARKERS = {
    ".docx": "word/",
    ".xlsx": "xl/",
    ".pptx": "ppt/",
}


def detect(filename: str, content_type: str | None) -> FileKind:
    """Identify the file from its name and declared MIME type; raise AppError if unsupported."""
    ext = os.path.splitext(filename or "")[1].lower()
    kind = KINDS.get(ext)
    if kind is None:
        raise AppError(415, "Unsupported file format.")
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime not in _GENERIC_MIMES and mime != kind.mime and mime not in kind.extra_mimes:
        # text/plain-ish for odd .txt senders is fine; everything else is a mismatch
        if not (kind.category == "txt" and mime.startswith("text/")):
            raise AppError(415, f"Invalid MIME type for a {kind.label} file ({mime}).")
    return kind


def verify_content(path: Path, kind: FileKind, display_name: str) -> None:
    """Check that the bytes really look like the claimed format (catches wrong/corrupt files)."""
    corrupt = AppError(
        422, f"{display_name} looks corrupted or is not a real {kind.label} file."
    )
    with open(path, "rb") as f:
        head = f.read(8192)
    if kind.ext == ".pdf":
        if b"%PDF-" not in head[:1024]:
            raise corrupt
    elif kind.ext in (".doc", ".xls", ".ppt"):
        if not head.startswith(_OLE):
            raise corrupt
    elif kind.ext in _OOXML_MARKERS:
        try:
            if not zipfile.is_zipfile(path):
                raise corrupt
            with zipfile.ZipFile(path) as z:
                names = z.namelist()
                if "[Content_Types].xml" not in names or not any(
                    n.startswith(_OOXML_MARKERS[kind.ext]) for n in names
                ):
                    raise corrupt
        except zipfile.BadZipFile:
            raise corrupt
    elif kind.ext == ".txt":
        if b"\x00" in head and not head.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise corrupt
