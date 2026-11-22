"""Final PDF generation and download."""
from fastapi import APIRouter
from fastapi.responses import Response

from backend.models import GenerateResponse
from backend.services import course_file_service as svc

router = APIRouter(prefix="/api/generate", tags=["generate"])


@router.post("", response_model=GenerateResponse)
def generate():
    info = svc.generate_final_pdf()
    return GenerateResponse(**info, download_url="/api/generate/download",
                            preview_url="/api/generate/download?inline=true")


@router.get("/download")
def download(inline: bool = False):
    data, name = svc.final_pdf()
    disposition = "inline" if inline else "attachment"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{name}"',
                             "Cache-Control": "private, no-store"})
