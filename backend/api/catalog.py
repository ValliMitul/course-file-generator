"""Catalog (courses + coordinators) and admin endpoints."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend import config
from backend.api.auth import require_admin
from backend.services import auth_service, catalog_service as svc

router = APIRouter(prefix="/api", tags=["catalog"])


class CourseIn(BaseModel):
    code: str = Field(max_length=60)
    name: str = Field(max_length=300)
    semester: str = Field(default="", max_length=10)


class CoordinatorIn(BaseModel):
    name: str = Field(max_length=200)
    designation: str = Field(default="", max_length=200)


class RoleIn(BaseModel):
    role: str


@router.get("/catalog")
def catalog():
    """Course codes -> names and the coordinator list (any signed-in user)."""
    return svc.get_catalog()


@router.post("/catalog/courses", status_code=201)
def add_course(body: CourseIn):
    return svc.add_course(body.code, body.name, body.semester, config.current_user.get())


@router.post("/catalog/coordinators", status_code=201)
def add_coordinator(body: CoordinatorIn):
    return svc.add_coordinator(body.name, body.designation, config.current_user.get())


@router.delete("/catalog/courses/{code}", dependencies=[Depends(require_admin)])
def delete_course(code: str):
    svc.delete_course(code)
    return {"ok": True}


@router.delete("/catalog/coordinators/{name}", dependencies=[Depends(require_admin)])
def delete_coordinator(name: str):
    svc.delete_coordinator(name)
    return {"ok": True}


# ----------------------------------------------------------------- admin
@router.get("/admin/users", dependencies=[Depends(require_admin)])
def admin_users():
    return {"users": auth_service.list_users(), "current": config.current_user.get()}


@router.put("/admin/users/{user_id}/role", dependencies=[Depends(require_admin)])
def admin_set_role(user_id: str, body: RoleIn):
    return auth_service.set_role(user_id, body.role, config.current_user.get())
