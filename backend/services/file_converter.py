"""Shared document -> PDF conversion service built on headless LibreOffice."""
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from backend import config
from backend.errors import AppError
from backend.services.file_detector import FileKind
from backend.utils.file_utils import remove_dir_quietly

log = logging.getLogger("cfg.converter")

LO_NOT_FOUND_MESSAGE = (
    "LibreOffice was not found. Please install LibreOffice or configure its executable path "
    f"(set the {config.LIBREOFFICE_ENV_VAR} environment variable to soffice.exe)."
)

_WINDOWS_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"C:\Program Files\LibreOffice 7\program\soffice.exe",
    r"C:\Program Files\LibreOffice 24\program\soffice.exe",
    r"C:\Program Files\LibreOffice 25\program\soffice.exe",
]


def find_libreoffice() -> str | None:
    """Locate soffice: env var, then PATH, then common Windows install folders."""
    env = os.environ.get(config.LIBREOFFICE_ENV_VAR, "").strip().strip('"')
    if env:
        p = Path(env)
        if p.is_dir():
            for name in ("soffice.exe", "soffice"):
                if (p / name).is_file():
                    return str(p / name)
        elif p.is_file():
            return str(p)
        log.warning("%s=%s does not point to a LibreOffice executable", config.LIBREOFFICE_ENV_VAR, env)
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    if sys.platform == "win32":
        for candidate in _WINDOWS_PATHS:
            if os.path.isfile(candidate):
                return candidate
    return None


def libreoffice_status() -> dict:
    path = find_libreoffice()
    if path:
        return {"available": True, "path": path, "message": "LibreOffice is available."}
    return {"available": False, "path": None, "message": LO_NOT_FOUND_MESSAGE}


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.kill()
    except Exception:  # pragma: no cover - best effort
        log.exception("Failed to kill LibreOffice process tree")


def _profile_uri(profile_dir: Path) -> str:
    return "-env:UserInstallation=" + profile_dir.resolve().as_uri()


def convert_to_pdf(source: Path, kind: FileKind, dest_pdf: Path, display_name: str) -> None:
    """Convert *source* to PDF at *dest_pdf* using headless LibreOffice.

    Each call uses its own temp working dir and LibreOffice profile so parallel or
    repeated conversions never hit profile-lock conflicts.
    """
    soffice = find_libreoffice()
    if not soffice:
        raise AppError(503, LO_NOT_FOUND_MESSAGE, code="libreoffice_missing")

    failure = AppError(422, f"Unable to convert {display_name} to PDF.")
    work = Path(tempfile.mkdtemp(prefix="conv_", dir=config.temp_dir()))
    try:
        # A neutral input name avoids problems with unusual characters in user filenames.
        input_copy = work / f"input{kind.ext}"
        shutil.copyfile(source, input_copy)
        out_dir = work / "out"
        out_dir.mkdir()
        profile = work / "profile"
        cmd = [
            soffice, "--headless", "--norestore", "--nolockcheck", "--nodefault",
            "--nologo", "--nofirststartwizard", _profile_uri(profile),
            "--convert-to", "pdf",  # LibreOffice picks the right export filter per document type
            "--outdir", str(out_dir), str(input_copy),
        ]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(  # noqa: S603 - argument list, no shell
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL, creationflags=flags,
            )
        except OSError:
            log.exception("Could not start LibreOffice at %s", soffice)
            raise AppError(503, LO_NOT_FOUND_MESSAGE, code="libreoffice_missing")
        try:
            stdout, stderr = proc.communicate(timeout=config.CONVERSION_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            proc.communicate()
            log.error("LibreOffice timed out converting %s", display_name)
            raise AppError(504, f"Converting {display_name} to PDF took too long and was cancelled.")

        produced = out_dir / "input.pdf"
        if proc.returncode != 0 or not produced.is_file() or produced.stat().st_size == 0:
            log.error("LibreOffice failed for %s (rc=%s): %s %s", display_name, proc.returncode,
                      stdout.decode(errors="replace"), stderr.decode(errors="replace"))
            raise failure
        try:
            PdfReader(str(produced))
        except (PyPdfError, OSError, ValueError):
            log.exception("LibreOffice produced an unreadable PDF for %s", display_name)
            raise failure
        dest_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), str(dest_pdf))
    finally:
        remove_dir_quietly(work)
