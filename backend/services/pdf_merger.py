"""Merge PDFs with pypdf and validate PDFs."""
import logging
import os
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.errors import PyPdfError

from backend.errors import AppError

log = logging.getLogger("cfg.merger")


def validate_pdf(path: Path, display_name: str) -> int:
    """Return the page count, or raise a friendly AppError for bad/encrypted PDFs."""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise AppError(422, f"{display_name} is password-protected. Please remove the password and upload it again.")
        pages = len(reader.pages)
    except AppError:
        raise
    except (PyPdfError, OSError, ValueError, KeyError, RecursionError):
        log.exception("Unreadable PDF: %s", display_name)
        raise AppError(422, f"{display_name} is not a valid PDF or is corrupted.")
    if pages == 0:
        raise AppError(422, f"{display_name} contains no pages.")
    return pages


def merge_pdfs(sources: list[tuple[str, Path]], dest: Path) -> int:
    """Append every page of each (display_name, path) in order. Returns total page count."""
    writer = PdfWriter()
    total = 0
    for name, path in sources:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                raise AppError(422, f"Unable to generate the final PDF because {name} is password-protected.")
            for page in reader.pages:
                writer.add_page(page)
                total += 1
        except AppError:
            raise
        except Exception:
            log.exception("Merge failed while reading %s", name)
            raise AppError(500, f"Unable to generate the final PDF because {name} could not be read.")
    if total == 0:
        raise AppError(400, "The assigned documents contain no pages.")
    tmp = dest.with_suffix(".tmp")
    try:
        with open(tmp, "wb") as f:
            writer.write(f)
        os.replace(tmp, dest)
    except Exception:
        log.exception("Failed writing final PDF")
        tmp.unlink(missing_ok=True)
        raise AppError(500, "Unable to generate the final PDF.")
    return total
