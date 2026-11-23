"""Default A-Z documents: every course file starts with the sample document in each section.

The 26 documents live in ``backend/assets/defaults`` (originals) and ``.../pdf`` (pre-converted).
Their blobs are uploaded to Appwrite Storage once and shared by everyone; each user just gets
26 library records pointing at them, so seeding is cheap and replacing a section never touches
the shared copy.
"""
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from appwrite.exception import AppwriteException
from appwrite.input_file import InputFile

from backend import config
from backend.services import appwrite_client, file_detector
from backend.utils.validation import LETTERS

log = logging.getLogger("cfg.defaults")
DIR = Path(__file__).resolve().parent.parent / "assets" / "defaults"
PDF_DIR = DIR / "pdf"
PREFIX = "dflt"
_ready = False
_lock = threading.Lock()


def _sources() -> dict[str, Path]:
    out = {}
    for f in sorted(DIR.iterdir()):
        if f.is_file() and f.name[:2] in {f"{l}_" for l in LETTERS}:
            out[f.name[0]] = f
    return out


def is_default(file_id: str) -> bool:
    return file_id.startswith(PREFIX)


def _blob(letter: str, kind: str) -> str:
    return f"{PREFIX}_{letter}_{kind}"        # kind: o = original, p = pdf


def ensure_blobs() -> None:
    """Upload the shared default blobs to Storage if they are not there yet (once per process)."""
    global _ready
    if _ready:
        return
    with _lock:
        if _ready:
            return
        st = appwrite_client.storage()
        try:
            st.get_file(config.APPWRITE_BUCKET_ID, _blob("Z", "p"))      # uploaded last => all present
            _ready = True
            return
        except AppwriteException as e:
            if e.code != 404:
                raise
        for letter, src in _sources().items():
            for kind, path in (("o", src), ("p", PDF_DIR / (src.stem + ".pdf"))):
                try:
                    st.create_file(config.APPWRITE_BUCKET_ID, _blob(letter, kind), InputFile.from_path(str(path)))
                except AppwriteException as e:
                    if e.code != 409:                  # 409 = already uploaded by an earlier partial run
                        raise
        _ready = True
        log.info("Default A-Z documents uploaded to storage")


def seeded(state: dict) -> bool:
    return any(is_default(f["id"]) for f in state["files"])


def seed(state: dict, user_id: str, describe) -> None:
    """Add the default library records and fill every EMPTY section with its default document."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    slots = {s["letter"]: s for s in state["slots"]}
    for letter, src in _sources().items():
        kind = file_detector.detect(src.name, None)
        rec = {
            "id": f"{PREFIX}{letter}_{user_id}"[:36], "original_name": src.name, "file_type": kind.label,
            "category": kind.category, "mime_type": kind.mime, "size": src.stat().st_size,
            "original_file_id": _blob(letter, "o"), "pdf_file_id": _blob(letter, "p"),
            "status": "ready", "uploaded_at": now,
        }
        state["files"].append(rec)
        slot = slots[letter]
        if not slot["file_id"]:
            slot["file_id"] = rec["id"]
            if not slot["description"].strip():
                slot["description"] = describe(rec)
