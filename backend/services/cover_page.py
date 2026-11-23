"""Build the cover page (first page of the final course file) from the official template.

``backend/assets/coverpage.docx`` is filled with the course details and the A-Z section
descriptions entered in the app, then converted to PDF with LibreOffice.
"""
import logging
import shutil
from pathlib import Path

from docx import Document

from backend.services import file_converter, file_detector

log = logging.getLogger("cfg.cover")
TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "coverpage.docx"
MAX_DESC_CHARS = 95          # keeps every A-Z row on one line so the cover stays a single page


def _set(cell, text: str) -> None:
    """Put *text* in a table cell, reusing the template's own run so the font is unchanged."""
    para = cell.paragraphs[0]
    if para.runs:
        para.runs[0].text = text
        for extra in para.runs[1:]:
            extra.text = ""
    else:
        para.add_run(text)


def _clip(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_DESC_CHARS else text[: MAX_DESC_CHARS - 1].rstrip() + "…"


def _join(parts: list[str], sep: str) -> str:
    return sep.join(p for p in (" ".join((x or "").split()) for x in parts) if p)


def fill_template(course: dict, slots: list[dict], dest_docx: Path) -> None:
    doc = Document(str(TEMPLATE))
    details, index = doc.tables[0], doc.tables[1]
    values = {
        "Course Code and Name": _join([course.get("course_code", ""), course.get("course_name", "")], " – "),
        "Program / School / Department": _join([course.get("department", "")], ""),
        "Semester / Academic Year": _join([course.get("semester", ""), course.get("academic_year", "")], " / "),
        "Name of Course Coordinator": _join([course.get("course_coordinator", "")], ""),
    }
    for row in details.rows:
        label = row.cells[0].text.strip().rstrip(":").strip()
        if label in values:
            _set(row.cells[1], values[label])

    # only sections that actually have a file are listed, matching the pages that follow
    desc = {s["letter"]: (s.get("description", "") if s.get("file_id") else "") for s in slots}
    for row in index.rows:
        letter = row.cells[0].text.strip()
        if len(letter) == 1 and letter in desc:
            _set(row.cells[1], _clip(desc[letter]))
    doc.save(str(dest_docx))


def build_cover_pdf(course: dict, slots: list[dict], work: Path, dest_pdf: Path) -> None:
    """Fill the template and convert it to *dest_pdf* (raises AppError if conversion fails)."""
    filled = work / "coverpage.docx"
    fill_template(course, slots, filled)
    kind = file_detector.detect("coverpage.docx", None)
    file_converter.convert_to_pdf(filled, kind, dest_pdf, "the cover page")
