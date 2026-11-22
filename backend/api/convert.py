"""Per-category conversion endpoints. All delegate to the shared conversion pipeline."""
from fastapi import APIRouter, File, UploadFile

from backend.models import FileOut
from backend.services import course_file_service as svc

router = APIRouter(prefix="/api/convert", tags=["convert"])


@router.post("/word", response_model=FileOut)
def convert_word(file: UploadFile = File(...)):
    """DOC/DOCX -> PDF. Returns the stored file info (preview at /api/files/{id}/preview)."""
    return svc.ingest_upload(file, expected_category="word")


@router.post("/excel", response_model=FileOut)
def convert_excel(file: UploadFile = File(...)):
    """XLS/XLSX -> PDF."""
    return svc.ingest_upload(file, expected_category="excel")


@router.post("/ppt", response_model=FileOut)
def convert_ppt(file: UploadFile = File(...)):
    """PPT/PPTX -> PDF."""
    return svc.ingest_upload(file, expected_category="ppt")


@router.post("/txt", response_model=FileOut)
def convert_txt(file: UploadFile = File(...)):
    """TXT -> PDF."""
    return svc.ingest_upload(file, expected_category="txt")


@router.post("/pdf", response_model=FileOut)
def validate_pdf_upload(file: UploadFile = File(...)):
    """PDF upload + validation only (no conversion needed)."""
    return svc.ingest_upload(file, expected_category="pdf")
