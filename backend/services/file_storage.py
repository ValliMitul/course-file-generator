"""Project-state persistence in Appwrite (TablesDB) and file blobs in Appwrite Storage.

* ``projects`` table - one row per faculty member (row id = Appwrite user id): course details,
  the 26 A-Z slots (JSON) and the last generated output.
* ``files`` table    - one row per uploaded document (library record).
* ``course-files`` bucket - original uploads, converted PDFs and the final merged PDF.

``ProjectStore`` keeps the small read()/update(mutate) interface the service layer uses.
Writes are serialised per user inside this process.
"""
import copy
import json
import logging
import threading
from pathlib import Path
from typing import Callable

from appwrite.exception import AppwriteException
from appwrite.input_file import InputFile
from appwrite.query import Query

from backend import config
from backend.errors import AppError
from backend.services import appwrite_client
from backend.utils.validation import LETTERS

log = logging.getLogger("cfg.storage")

COURSE_FIELDS = ["course_name", "course_code", "department", "semester",
                 "academic_year", "course_coordinator"]
FILE_FIELDS = ["original_name", "file_type", "category", "mime_type", "size", "status",
               "original_file_id", "pdf_file_id", "uploaded_at"]


def default_state() -> dict:
    return {
        "course": {k: "" for k in COURSE_FIELDS},
        "slots": [{"letter": l, "description": "", "file_id": None} for l in LETTERS],
        "files": [],
        "last_output": None,
    }


def _row(r) -> dict:
    """Flatten an SDK Row into {"$id": ..., <columns>...} whichever shape the SDK returns."""
    d = r if isinstance(r, dict) else r.to_dict()
    data = d.get("data") if isinstance(d.get("data"), dict) else {}
    return {**data, **{k: v for k, v in d.items() if k != "data"}}


def _normalise_slots(raw) -> list[dict]:
    """Make sure there are exactly 26 slots in A-Z order and a file sits in at most one."""
    try:
        stored = {s.get("letter"): s for s in (json.loads(raw) if raw else []) if isinstance(s, dict)}
    except (ValueError, TypeError):
        stored = {}
    used: set[str] = set()
    slots = []
    for letter in LETTERS:
        src = stored.get(letter, {})
        fid = src.get("file_id")
        if fid and fid in used:
            fid = None
        if fid:
            used.add(fid)
        slots.append({"letter": letter, "description": str(src.get("description", "")), "file_id": fid})
    return slots


def _wrap(action: str, fn):
    try:
        return fn()
    except AppwriteException as e:
        log.error("Appwrite error while %s: %s (code=%s type=%s)", action, e.message, e.code, e.type)
        raise AppError(502, "The storage service is not responding. Please try again in a moment.")


# ------------------------------------------------------------------ blobs
def put_blob(file_id: str, path: Path, name: str) -> None:
    def go():
        appwrite_client.storage().create_file(config.APPWRITE_BUCKET_ID, file_id, InputFile.from_path(str(path)))
    _wrap(f"uploading {name}", go)


def get_blob(file_id: str) -> bytes:
    try:
        return appwrite_client.storage().get_file_download(config.APPWRITE_BUCKET_ID, file_id)
    except AppwriteException as e:
        if e.code == 404:
            raise AppError(404, "The stored file is missing. Please upload it again.")
        log.error("Appwrite error downloading %s: %s", file_id, e.message)
        raise AppError(502, "The storage service is not responding. Please try again in a moment.")


def delete_blob(file_id: str) -> None:
    try:
        appwrite_client.storage().delete_file(config.APPWRITE_BUCKET_ID, file_id)
    except AppwriteException as e:
        if e.code != 404:
            log.warning("Could not delete blob %s: %s", file_id, e.message)


# ------------------------------------------------------------------ store
_locks: dict[str, threading.RLock] = {}
_locks_guard = threading.Lock()


def _lock_for(user_id: str) -> threading.RLock:
    with _locks_guard:
        return _locks.setdefault(user_id, threading.RLock())


class ProjectStore:
    """State of one faculty member's course file, persisted in Appwrite."""

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.lock = _lock_for(user_id)

    # -- reading
    def _load(self) -> dict:
        db = appwrite_client.db()
        state = default_state()
        try:
            row = _row(db.get_row(config.APPWRITE_DATABASE_ID, config.APPWRITE_PROJECTS_TABLE, self.user_id))
        except AppwriteException as e:
            if e.code != 404:
                raise
            row = None
            db.create_row(config.APPWRITE_DATABASE_ID, config.APPWRITE_PROJECTS_TABLE, self.user_id,
                          self._project_data(state), permissions=[])
        if row:
            for k in COURSE_FIELDS:
                state["course"][k] = str(row.get(k) or "")
            state["slots"] = _normalise_slots(row.get("slots"))
            try:
                lo = json.loads(row["last_output"]) if row.get("last_output") else None
            except ValueError:
                lo = None
            state["last_output"] = lo if isinstance(lo, dict) and lo.get("filename") else None
        files = []
        offset = 0
        while True:
            page = db.list_rows(config.APPWRITE_DATABASE_ID, config.APPWRITE_FILES_TABLE, [
                Query.equal("user_id", [self.user_id]), Query.order_asc("$createdAt"),
                Query.limit(100), Query.offset(offset)])
            rows = [_row(r) for r in page.rows]
            for r in rows:
                files.append({"id": r["$id"], **{k: r.get(k) for k in FILE_FIELDS}})
            if len(rows) < 100:
                break
            offset += 100
        ids = {f["id"] for f in files}
        for s in state["slots"]:
            if s["file_id"] not in ids:
                s["file_id"] = None
        state["files"] = files
        return state

    def read(self) -> dict:
        with self.lock:
            return _wrap("reading the project", self._load)

    # -- writing
    def _project_data(self, state: dict) -> dict:
        data = {"user_id": self.user_id, **{k: state["course"].get(k, "") for k in COURSE_FIELDS},
                "slots": json.dumps(state["slots"], ensure_ascii=False),
                "last_output": json.dumps(state["last_output"]) if state["last_output"] else ""}
        return data

    def update(self, mutate: Callable[[dict], object]):
        """Read the current state, apply *mutate*, and persist only what changed.

        If *mutate* raises, nothing is written.
        """
        with self.lock:
            def go():
                old = self._load()
                new = copy.deepcopy(old)
                result = mutate(new)
                db = appwrite_client.db()
                old_ids = {f["id"] for f in old["files"]}
                for f in new["files"]:
                    if f["id"] not in old_ids:
                        data = {"user_id": self.user_id, **{k: f.get(k) for k in FILE_FIELDS}}
                        data["size"] = int(data["size"])
                        db.create_row(config.APPWRITE_DATABASE_ID, config.APPWRITE_FILES_TABLE,
                                      f["id"], data, permissions=[])
                if self._project_data(new) != self._project_data(old):
                    db.update_row(config.APPWRITE_DATABASE_ID, config.APPWRITE_PROJECTS_TABLE,
                                  self.user_id, self._project_data(new))
                return result
            return _wrap("saving the project", go)
