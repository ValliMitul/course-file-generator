"""Course details and A-Z slot endpoints."""
from fastapi import APIRouter, File, Form, UploadFile

from backend.models import (
    AssignRequest, CourseDetails, DescriptionUpdate, SnapshotOut, SwapRequest,
)
from backend.services import course_file_service as svc

router = APIRouter(prefix="/api", tags=["slots"])


@router.get("/slots", response_model=SnapshotOut)
def get_slots():
    """Full project state: course details, the 26 slots (A-Z), files and summary."""
    return svc.snapshot()


@router.put("/project", response_model=SnapshotOut)
def update_project(details: CourseDetails):
    return svc.update_course(details)


# NOTE: declared before /slots/{letter} routes so "swap" is never treated as a letter.
@router.post("/slots/swap", response_model=SnapshotOut)
def swap_slots(body: SwapRequest):
    """Swap the CONTENT (description + file) of two slots. Letters never move."""
    return svc.swap(body.from_letter, body.to_letter)


@router.put("/slots/{letter}", response_model=SnapshotOut)
def update_slot(letter: str, body: DescriptionUpdate):
    return svc.set_description(letter, body.description)


@router.post("/slots/{letter}/assign", response_model=SnapshotOut)
def assign_to_slot(letter: str, body: AssignRequest):
    """Assign an already-uploaded file. Returns 409 unless ``force`` when replacing/moving."""
    return svc.assign(letter, body.file_id, body.force)


@router.post("/slots/{letter}/upload", response_model=SnapshotOut)
def upload_to_slot(letter: str, file: UploadFile = File(...), replace: bool = Form(False)):
    """Upload a new file straight into a slot. 409 if occupied unless ``replace`` is true."""
    return svc.upload_to_slot(letter, file, replace)
