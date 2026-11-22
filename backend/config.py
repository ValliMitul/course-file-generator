"""Central configuration: Appwrite connection, limits and scratch space.

Settings come from environment variables (a local ``.env`` file is loaded for development;
on a host, set them in the platform's environment settings). Nothing is stored on local disk
except short-lived scratch files used while converting documents.
"""
import os
import tempfile
from contextvars import ContextVar
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"
load_dotenv(BASE_DIR / ".env")

# ---- Appwrite -------------------------------------------------------------
APPWRITE_ENDPOINT = os.environ.get("APPWRITE_ENDPOINT", "https://cloud.appwrite.io/v1")
APPWRITE_PROJECT_ID = os.environ.get("APPWRITE_PROJECT_ID", "")
APPWRITE_API_KEY = os.environ.get("APPWRITE_API_KEY", "")   # server-side secret, never sent to the browser
APPWRITE_DATABASE_ID = os.environ.get("APPWRITE_DATABASE_ID", "coursefile")
APPWRITE_PROJECTS_TABLE = os.environ.get("APPWRITE_PROJECTS_TABLE", "projects")
APPWRITE_FILES_TABLE = os.environ.get("APPWRITE_FILES_TABLE", "files")
APPWRITE_BUCKET_ID = os.environ.get("APPWRITE_BUCKET_ID", "course-files")

# Roles are Appwrite user labels (labels can only be set server-side, never by the user):
#   "faculty" - normal user.  "admin" - faculty rights plus catalog deletes and user management.
FACULTY_LABEL = os.environ.get("CFG_FACULTY_LABEL", "faculty")
ADMIN_LABEL = os.environ.get("CFG_ADMIN_LABEL", "admin")
ROLES = (ADMIN_LABEL, FACULTY_LABEL)
# Optional sign-up allow-list, e.g. "pdpu.ac.in,sot.pdpu.ac.in". Empty = anyone can sign up as faculty.
SIGNUP_DOMAINS = [d.strip().lower().lstrip("@") for d in os.environ.get("CFG_SIGNUP_DOMAINS", "").split(",") if d.strip()]
APPWRITE_COURSES_TABLE = os.environ.get("APPWRITE_COURSES_TABLE", "courses")
APPWRITE_COORDINATORS_TABLE = os.environ.get("APPWRITE_COORDINATORS_TABLE", "coordinators")
SESSION_DAYS = 30

# Appwrite's free plan caps a single file at 50,000,000 bytes.
MAX_UPLOAD_BYTES = int(os.environ.get("CFG_MAX_UPLOAD_BYTES", 50_000_000))
CONVERSION_TIMEOUT_SECONDS = 180
MAX_DESCRIPTION_LENGTH = 300
MAX_COURSE_FIELD_LENGTH = 200

# Environment variable that may point at soffice.exe (or the LibreOffice "program" folder)
LIBREOFFICE_ENV_VAR = "LIBREOFFICE_PATH"

# Frontend on another origin (e.g. Appwrite Sites): comma-separated origins allowed to call the API,
# e.g. "https://courses.appwrite.network". Leave empty when FastAPI serves the frontend itself.
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("CFG_ALLOWED_ORIGINS", "").split(",") if o.strip()]
# "lax" when frontend and API share a site (same registrable domain); "none" for a different site.
COOKIE_SAMESITE = os.environ.get("CFG_COOKIE_SAMESITE", "lax" if not ALLOWED_ORIGINS else "none").lower()

# Set to 0 to allow the session cookie over plain http (local development only).
COOKIE_SECURE_AUTO = os.environ.get("CFG_COOKIE_SECURE_AUTO", "1") == "1"

# Scratch space for conversions/merges (ephemeral; safe to lose on restart).
TEMP_DIR = Path(os.environ.get("CFG_TEMP_DIR") or Path(tempfile.gettempdir()) / "course-file-generator").resolve()

# The authenticated Appwrite user id for the current request (set by the auth dependency).
current_user: ContextVar[str | None] = ContextVar("current_user", default=None)
current_role: ContextVar[str | None] = ContextVar("current_role", default=None)


def temp_dir() -> Path:
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR


def appwrite_configured() -> bool:
    return bool(APPWRITE_PROJECT_ID and APPWRITE_API_KEY)
