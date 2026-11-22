"""Upload and file-library endpoints."""
import logging

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import Response

from backend.errors import AppError
from backend.models import FileOut, UploadResponse, UploadResult
from backend.services import course_file_service as svc

log = logging.getLogger("cfg.api.upload")
router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/upload", response_model=UploadResponse)
def upload_files(files: list[UploadFile] = File(...)):
    """Upload one or more files. Each is detected, converted if needed and stored.

    A failure on one file does not stop the others; see ``results`` for per-file outcomes.
    """
    results: list[UploadResult] = []
    for f in files:
        name = f.filename or "(unnamed)"
        try:
            results.append(UploadResult(filename=name, ok=True, file=svc.ingest_upload(f)))
        except AppError as e:
            log.warning("Upload rejected for %s: %s", name, e.message)
            results.append(UploadResult(filename=name, ok=False, error=e.message))
        except Exception:
            log.exception("Unexpected error while uploading %s", name)
            results.append(UploadResult(filename=name, ok=False,
                                        error=f"Unable to process {name}."))
    return UploadResponse(results=results)


@router.get("", response_model=list[FileOut])
def list_files():
    return svc.list_files()


@router.get("/{file_id}", response_model=FileOut)
def get_file(file_id: str):
    return svc.get_file(file_id)


@router.get("/{file_id}/preview")
def preview_file(file_id: str):
    """Serve the normalised PDF (converted PDF, or the original for PDFs) for PDF.js."""
    data, name = svc.preview_pdf(file_id)
    pdf_name = f"{name.rsplit('.', 1)[0]}.pdf".encode("ascii", "replace").decode().replace('"', "")
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pdf_name}"',
                             "Cache-Control": "private, no-store"})
