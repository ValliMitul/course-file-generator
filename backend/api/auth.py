"""Login/logout endpoints and the dependency that protects the rest of the API."""
from fastapi import APIRouter, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend import config
from backend.errors import AppError
from backend.services import auth_service

COOKIE = "cfg_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login_id: str = ""      # the faculty member's email address
    password: str = ""


class UserOut(BaseModel):
    name: str


def _unauth() -> AppError:
    return AppError(401, "Please log in.", code="not_authenticated")


async def require_user(request: Request) -> str:
    """Dependency: validate the Appwrite session cookie and bind the user to this request.

    Async on purpose: the ContextVar must be set in the request's own context so the sync
    endpoint (run in a worker thread with a copy of that context) can see it. The blocking
    Appwrite call itself runs in the thread pool.
    """
    who = await run_in_threadpool(auth_service.verify_session, request.cookies.get(COOKIE))
    if not who:
        raise _unauth()
    config.current_user.set(who[0])
    return who[1]


@router.post("/login", response_model=UserOut)
def login(body: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    if auth_service.too_many_attempts(ip):
        raise AppError(429, "Too many failed attempts. Please wait a few minutes and try again.")
    try:
        secret, _user_id, name = auth_service.login(body.login_id, body.password)
    except AppError as e:
        if e.code in ("bad_credentials", "not_faculty"):
            auth_service.record_failure(ip)
        raise
    secure = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
              if config.COOKIE_SECURE_AUTO else False)
    response.set_cookie(COOKIE, secret, max_age=config.SESSION_DAYS * 86400,
                        httponly=True, samesite=config.COOKIE_SAMESITE, secure=secure or config.COOKIE_SAMESITE == "none",
                        path="/")
    return UserOut(name=name)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth_service.logout(request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(request: Request):
    who = auth_service.verify_session(request.cookies.get(COOKIE))
    if not who:
        raise _unauth()
    return UserOut(name=who[1])
