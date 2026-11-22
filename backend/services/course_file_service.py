"""Business logic: uploads, slot assignment, drag swaps and final PDF generation."""
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

from backend import config
from backend.errors import AppError
from backend.models import CourseDetails
from backend.services import file_detector, file_converter, file_storage, pdf_merger
from backend.services.file_storage import COURSE_FIELDS, ProjectStore
from backend.utils.file_utils import sanitize_filename, sanitize_for_output, save_upload
from backend.utils.validation import validate_file_id, validate_letter

log = logging.getLogger("cfg.service")


class _StoreProxy:
    """The ProjectStore of the faculty member making the current request."""

    def __getattr__(self, name):
        user = config.current_user.get()
        if not user:
            raise AppError(401, "Please log in.", code="not_authenticated")
        return getattr(ProjectStore(user), name)


store = _StoreProxy()


# ----------------------------------------------------------------- helpers
def _find_file(state: dict, file_id: str) -> dict | None:
    return next((f for f in state["files"] if f["id"] == file_id), None)


def _slot(state: dict, letter: str) -> dict:
    # Slots are indexed by their fixed A-Z position; positions are never changed.
    return state["slots"][ord(letter) - ord("A")]


def _assigned_letter(state: dict, file_id: str) -> str | None:
    return next((s["letter"] for s in state["slots"] if s["file_id"] == file_id), None)


def _file_out(state: dict, f: dict) -> dict:
    return {
        "id": f["id"], "original_name": f["original_name"], "file_type": f["file_type"],
        "category": f["category"], "mime_type": f["mime_type"], "size": f["size"],
        "status": f["status"], "assigned_to": _assigned_letter(state, f["id"]),
    }


def snapshot() -> dict:
    state = store.read()
    files = [_file_out(state, f) for f in state["files"]]
    by_id = {f["id"]: f for f in files}
    slots = [{"letter": s["letter"], "description": s["description"], "file_id": s["file_id"],
              "file": by_id.get(s["file_id"])} for s in state["slots"]]
    assigned = sum(1 for s in slots if s["file_id"])
    return {
        "course": state["course"], "slots": slots, "files": files,
        "summary": {"total_files": len(files), "assigned_files": assigned,
                    "empty_sections": 26 - assigned},
        "last_output": state.get("last_output"),
    }


def list_files() -> list[dict]:
    return snapshot()["files"]


def get_file(file_id: str) -> dict:
    file_id = validate_file_id(file_id)
    state = store.read()
    rec = _find_file(state, file_id)
    if not rec:
        raise AppError(404, "File not found.")
    return _file_out(state, rec)


# ------------------------------------------------------------ course/slots
def update_course(details: CourseDetails) -> dict:
    def mutate(state):
        for k in COURSE_FIELDS:
            state["course"][k] = getattr(details, k).strip()[: config.MAX_COURSE_FIELD_LENGTH]
    store.update(mutate)
    return snapshot()


def set_description(letter: str, description: str) -> dict:
    letter = validate_letter(letter)
    text = description.strip()[: config.MAX_DESCRIPTION_LENGTH]
    store.update(lambda state: _slot(state, letter).__setitem__("description", text))
    return snapshot()


def _default_description(rec: dict) -> str:
    """The file name without its extension - the default description of a section."""
    return os.path.splitext(rec["original_name"])[0].strip()[: config.MAX_DESCRIPTION_LENGTH]


def _apply_assign(state: dict, letter: str, file_id: str, force: bool) -> None:
    rec = _find_file(state, file_id)
    if not rec:
        raise AppError(404, "File not found.")
    if rec["status"] != "ready":
        raise AppError(409, f"{rec['original_name']} is not ready to be assigned.")
    slot = _slot(state, letter)
    if slot["file_id"] == file_id:
        return
    other = _assigned_letter(state, file_id)
    if not force:
        if other:
            raise AppError(409, f"This file is already assigned to section {other}. "
                                f"Do you want to move it to section {letter}?",
                           code="file_assigned_elsewhere")
        if slot["file_id"]:
            cur = _find_file(state, slot["file_id"])
            raise AppError(409, f"Section {letter} already contains {cur['original_name'] if cur else 'a file'}. "
                                "Do you want to replace it?", code="slot_occupied")
    prev = _find_file(state, slot["file_id"]) if slot["file_id"] else None
    if other:
        old = _slot(state, other)
        moved = _find_file(state, old["file_id"])
        if moved and old["description"].strip() == _default_description(moved):
            old["description"] = ""            # the auto-filled name leaves with its file
        old["file_id"] = None                  # moving: free the old section
    # Default the description to the file's name, but never overwrite text the user typed
    # (an earlier auto-filled name may be replaced along with its file).
    current = slot["description"].strip()
    if not current or (prev and current == _default_description(prev)):
        slot["description"] = _default_description(rec)
    slot["file_id"] = file_id                   # replaced file simply becomes unassigned


def assign(letter: str, file_id: str, force: bool) -> dict:
    letter = validate_letter(letter)
    file_id = validate_file_id(file_id)
    store.update(lambda state: _apply_assign(state, letter, file_id, force))
    return snapshot()


def swap(from_letter: str, to_letter: str) -> dict:
    a, b = validate_letter(from_letter), validate_letter(to_letter)
    if a == b:
        return snapshot()

    def mutate(state):
        sa, sb = _slot(state, a), _slot(state, b)
        empty = lambda s: not s["file_id"] and not s["description"].strip()
        if empty(sa) and empty(sb):
            return
        # Only the CONTENT (description + file) moves; the letters never change.
        sa["description"], sb["description"] = sb["description"], sa["description"]
        sa["file_id"], sb["file_id"] = sb["file_id"], sa["file_id"]

    store.update(mutate)
    return snapshot()


# ----------------------------------------------------------------- uploads
def _final_blob_id() -> str:
    return f"out_{config.current_user.get()}"[:36]


def ingest_upload(upload: UploadFile, expected_category: str | None = None) -> dict:
    """Validate, convert (if needed) and store one upload in Appwrite. Returns the file record."""
    display = sanitize_filename(upload.filename)
    if not display:
        raise AppError(400, "The uploaded file has no name.")
    kind = file_detector.detect(display, upload.content_type)
    if expected_category and kind.category != expected_category:
        label = file_detector.CATEGORY_LABELS[expected_category]
        raise AppError(400, f"This endpoint only accepts {label} files, but {display} is a {kind.label} file.")

    file_id = uuid.uuid4().hex
    original_blob = file_id
    pdf_blob = file_id if kind.category == "pdf" else uuid.uuid4().hex
    uploaded: list[str] = []
    work = Path(tempfile.mkdtemp(prefix="up_", dir=config.temp_dir()))   # scratch only; always removed
    try:
        original = work / f"{file_id}{kind.ext}"
        size = save_upload(upload, original)
        file_detector.verify_content(original, kind, display)
        if kind.category == "pdf":
            pdf_merger.validate_pdf(original, display)
            converted = original            # PDFs need no conversion
        else:
            converted = work / f"{pdf_blob}.pdf"
            file_converter.convert_to_pdf(original, kind, converted, display)

        file_storage.put_blob(original_blob, original, display)
        uploaded.append(original_blob)
        if pdf_blob != original_blob:
            file_storage.put_blob(pdf_blob, converted, display)
            uploaded.append(pdf_blob)

        record = {
            "id": file_id, "original_name": display, "file_type": kind.label,
            "category": kind.category, "mime_type": kind.mime, "size": size,
            "original_file_id": original_blob, "pdf_file_id": pdf_blob, "status": "ready",
            "uploaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        store.update(lambda state: state["files"].append(record))
    except Exception:
        for blob in uploaded:               # don't leave orphans in storage
            file_storage.delete_blob(blob)
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return get_file(file_id)


def upload_to_slot(letter: str, upload: UploadFile, replace: bool) -> dict:
    letter = validate_letter(letter)
    state = store.read()
    current = _slot(state, letter)["file_id"]
    if current and not replace:
        cur = _find_file(state, current)
        raise AppError(409, f"Section {letter} already contains {cur['original_name'] if cur else 'a file'}. "
                            "Do you want to replace it?", code="slot_occupied")
    rec = ingest_upload(upload)
    store.update(lambda s: _apply_assign(s, letter, rec["id"], True))
    return snapshot()


def preview_pdf(file_id: str) -> tuple[bytes, str]:
    """The normalised PDF bytes (converted PDF, or the original for PDFs) and the file's name."""
    file_id = validate_file_id(file_id)
    rec = _find_file(store.read(), file_id)
    if not rec:
        raise AppError(404, "File not found.")
    return file_storage.get_blob(rec["pdf_file_id"]), rec["original_name"]


# ------------------------------------------------------------- final PDF
def output_filename(course_code: str) -> str:
    code = sanitize_for_output(course_code.strip())
    return f"{code}_Course_File.pdf" if code else "FINAL_COURSE_FILE.pdf"


def generate_final_pdf() -> dict:
    state = store.read()
    plan: list[tuple[str, str, str]] = []     # (display name, pdf blob id, letter) in A-Z order
    for slot in state["slots"]:               # fixed A-Z order, never upload order
        fid = slot["file_id"]
        if not fid:
            continue                          # empty sections are skipped
        rec = _find_file(state, fid)
        if not rec:
            raise AppError(409, "Unable to generate the final PDF because one of the assigned files is missing.")
        plan.append((rec["original_name"], rec["pdf_file_id"], slot["letter"]))
    if not plan:
        raise AppError(400, "No files are assigned to any section yet. Assign at least one file first.")

    name = output_filename(state["course"].get("course_code", ""))
    work = Path(tempfile.mkdtemp(prefix="gen_", dir=config.temp_dir()))
    try:
        sources: list[tuple[str, Path]] = []
        for i, (orig, blob, letter) in enumerate(plan):
            try:
                data = file_storage.get_blob(blob)
            except AppError as e:
                if e.status_code == 404:
                    raise AppError(409, "Unable to generate the final PDF because one of the assigned files "
                                        f"is missing ({orig}, section {letter}).")
                raise
            part = work / f"{i:02d}.pdf"
            part.write_bytes(data)
            sources.append((orig, part))
        dest = work / "final.pdf"
        pages = pdf_merger.merge_pdfs(sources, dest)

        blob_id = _final_blob_id()
        file_storage.delete_blob(blob_id)     # one final PDF per user; replace the previous one
        file_storage.put_blob(blob_id, dest, name)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    info = {"filename": name, "total_documents": len(plan), "total_pages": pages}
    store.update(lambda s: s.__setitem__("last_output", info))
    return info


def final_pdf() -> tuple[bytes, str]:
    info = store.read().get("last_output")
    if not info:
        raise AppError(404, "No final PDF has been generated yet.")
    try:
        data = file_storage.get_blob(_final_blob_id())
    except AppError as e:
        if e.status_code == 404:
            raise AppError(404, "The final PDF is missing. Please generate it again.")
        raise
    return data, info["filename"]
