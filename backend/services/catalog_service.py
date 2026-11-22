"""Shared catalog of course codes/names and course coordinators (faculty directory).

Stored in Appwrite tables ``courses`` and ``coordinators``. Both are seeded once from
``backend/data/catalog_seed.json`` (built from the PDEU CSE spreadsheets) when empty.
Any signed-in user may add entries; only administrators may delete them.
"""
import hashlib
import json
import logging
import re
import threading
from pathlib import Path

from appwrite.exception import AppwriteException
from appwrite.query import Query

from backend import config
from backend.errors import AppError
from backend.services import appwrite_client
from backend.services.file_storage import _row, _wrap

log = logging.getLogger("cfg.catalog")
SEED = Path(__file__).resolve().parent.parent / "data" / "catalog_seed.json"
SEMESTERS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]
CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{1,39}$")
_seed_lock = threading.Lock()
_seeded = False


def _id(kind: str, key: str) -> str:
    return hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:32]


def _norm_code(code: str) -> str:
    return "".join((code or "").split()).upper()


def _norm_name(name: str) -> str:
    return " ".join((name or "").split())


def _list_all(table: str, order: str) -> list[dict]:
    db, out, offset = appwrite_client.db(), [], 0
    while True:
        page = db.list_rows(config.APPWRITE_DATABASE_ID, table,
                            [Query.order_asc(order), Query.limit(100), Query.offset(offset)])
        rows = [_row(r) for r in page.rows]
        out += rows
        if len(rows) < 100:
            return out
        offset += 100


def _create(table: str, row_id: str, data: dict) -> bool:
    """Create a row; return False if it already exists."""
    try:
        appwrite_client.db().create_row(config.APPWRITE_DATABASE_ID, table, row_id, data, permissions=[])
        return True
    except AppwriteException as e:
        if e.code == 409:
            return False
        raise


def ensure_seeded() -> None:
    """Fill empty catalog tables from the bundled seed (safe to call repeatedly)."""
    global _seeded
    if _seeded:
        return
    with _seed_lock:
        if _seeded:
            return
        seed = json.loads(SEED.read_text(encoding="utf-8")) if SEED.is_file() else {"courses": [], "coordinators": []}
        db = appwrite_client.db()
        for table, key, items, build in (
            (config.APPWRITE_COURSES_TABLE, "course", seed["courses"],
             lambda c: (_id("course", c["code"]), {"code": c["code"], "name": c["name"],
                                                   "semester": c.get("semester", ""), "added_by": "seed"})),
            (config.APPWRITE_COORDINATORS_TABLE, "coordinator", seed["coordinators"],
             lambda c: (_id("coordinator", c["name"].lower()),
                        {"name": c["name"], "designation": c.get("designation", ""), "added_by": "seed"})),
        ):
            existing = db.list_rows(config.APPWRITE_DATABASE_ID, table, [Query.limit(1)])
            if existing.total and existing.total > 0:
                continue
            for item in items:
                rid, data = build(item)
                _create(table, rid, data)
            log.info("Seeded %d %s rows", len(items), key)
        _seeded = True


def get_catalog() -> dict:
    def go():
        ensure_seeded()
        courses = [{"code": r["code"], "name": r["name"], "semester": r.get("semester") or ""}
                   for r in _list_all(config.APPWRITE_COURSES_TABLE, "code")]
        people = [{"name": r["name"], "designation": r.get("designation") or ""}
                  for r in _list_all(config.APPWRITE_COORDINATORS_TABLE, "name")]
        return {"courses": courses, "coordinators": people, "semesters": SEMESTERS}
    return _wrap("reading the catalog", go)


def add_course(code: str, name: str, semester: str, user_id: str) -> dict:
    code, name, semester = _norm_code(code), _norm_name(name), (semester or "").strip().upper()
    if not CODE_RE.match(code):
        raise AppError(400, "Enter a valid course code (letters, digits, - . / only), e.g. 20CP101T.")
    if not (2 <= len(name) <= 200):
        raise AppError(400, "Enter the course name.")
    if semester and semester not in SEMESTERS:
        raise AppError(400, "Semester must be I to VIII.")

    def go():
        if not _create(config.APPWRITE_COURSES_TABLE, _id("course", code),
                       {"code": code, "name": name, "semester": semester, "added_by": user_id}):
            raise AppError(409, f"Course code {code} already exists.", code="exists")
        return {"code": code, "name": name, "semester": semester}
    return _wrap("adding the course", go)


def add_coordinator(name: str, designation: str, user_id: str) -> dict:
    name, designation = _norm_name(name), _norm_name(designation)[:80]
    if not (2 <= len(name) <= 120):
        raise AppError(400, "Enter the coordinator's full name.")

    def go():
        if not _create(config.APPWRITE_COORDINATORS_TABLE, _id("coordinator", name.lower()),
                       {"name": name, "designation": designation, "added_by": user_id}):
            raise AppError(409, f"{name} is already in the list.", code="exists")
        return {"name": name, "designation": designation}
    return _wrap("adding the coordinator", go)


def delete_course(code: str) -> None:
    _delete(config.APPWRITE_COURSES_TABLE, _id("course", _norm_code(code)))


def delete_coordinator(name: str) -> None:
    _delete(config.APPWRITE_COORDINATORS_TABLE, _id("coordinator", _norm_name(name).lower()))


def _delete(table: str, row_id: str) -> None:
    def go():
        try:
            appwrite_client.db().delete_row(config.APPWRITE_DATABASE_ID, table, row_id)
        except AppwriteException as e:
            if e.code != 404:
                raise
            raise AppError(404, "That entry was not found.")
    _wrap("deleting the entry", go)
