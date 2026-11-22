"""Pydantic request/response models."""
from pydantic import BaseModel, Field


class CourseDetails(BaseModel):
    course_name: str = ""
    course_code: str = ""
    department: str = ""
    semester: str = ""
    academic_year: str = ""
    course_coordinator: str = ""


class FileOut(BaseModel):
    id: str
    original_name: str
    file_type: str          # e.g. "DOCX"
    category: str           # pdf | word | excel | ppt | txt
    mime_type: str
    size: int
    status: str             # ready | failed
    assigned_to: str | None = None


class SlotOut(BaseModel):
    letter: str
    description: str
    file_id: str | None
    file: FileOut | None = None


class Summary(BaseModel):
    total_files: int
    assigned_files: int
    empty_sections: int


class LastOutput(BaseModel):
    filename: str
    total_documents: int
    total_pages: int


class SnapshotOut(BaseModel):
    course: CourseDetails
    slots: list[SlotOut]
    files: list[FileOut]
    summary: Summary
    last_output: LastOutput | None = None


class UploadResult(BaseModel):
    filename: str
    ok: bool
    file: FileOut | None = None
    error: str | None = None


class UploadResponse(BaseModel):
    results: list[UploadResult]


class DescriptionUpdate(BaseModel):
    description: str = Field(default="")


class AssignRequest(BaseModel):
    file_id: str
    force: bool = False


class SwapRequest(BaseModel):
    from_letter: str = Field(alias="from")
    to_letter: str = Field(alias="to")

    model_config = {"populate_by_name": True}


class GenerateResponse(BaseModel):
    filename: str
    total_documents: int
    total_pages: int
    download_url: str
    preview_url: str


class LibreOfficeStatus(BaseModel):
    available: bool
    path: str | None = None
    message: str


class HealthResponse(BaseModel):
    status: str
    appwrite_configured: bool = False
    libreoffice: LibreOfficeStatus
