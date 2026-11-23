"""Sign-in / sign-up / sign-out endpoints and the role-aware dependencies protecting the API."""
from fastapi import APIRouter, Depends, Request, Response
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend import config
from backend.errors import AppError
from backend.services import auth_service

COOKIE = "cfg_session"
router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    login_id: str = ""      # the user's email address
    password: str = ""


class SignupRequest(BaseModel):
    name: str = ""
    email: str = ""
    password: str = ""


class UserOut(BaseModel):
    name: str
    role: str               # "faculty" | "admin"


class LoginOut(UserOut):
    # Same session secret as the cookie. Sent back so the website can also use it in an Authorization
    # header: browsers that block third-party cookies would otherwise bounce the user to the login page.
    token: str


def _unauth() -> AppError:
    return AppError(401, "Please log in.", code="not_authenticated")


def _secret(request: Request) -> str | None:
    """The session secret: Authorization header first, then the cookie."""
    h = request.headers.get("authorization", "")
    if h[:7].lower() == "bearer " and h[7:].strip():
        return h[7:].strip()
    return request.cookies.get(COOKIE)


async def require_user(request: Request) -> str:
    """Dependency: validate the Appwrite session cookie and bind user + role to this request.

    Async on purpose: the ContextVars must be set in the request's own context so the sync
    endpoint (run in a worker thread with a copy of that context) can see them. The blocking
    Appwrite call itself runs in the thread pool.
    """
    who = await run_in_threadpool(auth_service.verify_session, _secret(request))
    if not who:
        raise _unauth()
    config.current_user.set(who[0])
    config.current_role.set(who[2])
    return who[1]


async def require_admin(_: str = Depends(require_user)) -> None:
    if config.current_role.get() != "admin":
        raise AppError(403, "Only an administrator can do this.", code="admin_only")


def _start_session(request: Request, response: Response, secret: str) -> None:
    secure = (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
              if config.COOKIE_SECURE_AUTO else False)
    response.set_cookie(COOKIE, secret, max_age=config.SESSION_DAYS * 86400,
                        httponly=True, samesite=config.COOKIE_SAMESITE,
                        secure=secure or config.COOKIE_SAMESITE == "none", path="/")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@router.post("/login", response_model=LoginOut)
def login(body: LoginRequest, request: Request, response: Response):
    ip = _ip(request)
    if auth_service.too_many_attempts(ip):
        raise AppError(429, "Too many failed attempts. Please wait a few minutes and try again.")
    try:
        secret, _uid, name, role = auth_service.login(body.login_id, body.password)
    except AppError as e:
        if e.code in ("bad_credentials", "no_role"):
            auth_service.record_failure(ip)
        raise
    _start_session(request, response, secret)
    return LoginOut(name=name, role=role, token=secret)


@router.post("/signup", response_model=LoginOut)
def signup(body: SignupRequest, request: Request, response: Response):
    """Create a faculty account and sign in. The admin role cannot be requested here."""
    ip = _ip(request)
    if auth_service.too_many_attempts(ip):
        raise AppError(429, "Too many attempts. Please wait a few minutes and try again.")
    auth_service.record_failure(ip)      # sign-ups count toward the same limiter to slow abuse
    secret, _uid, name, role = auth_service.signup(body.name, body.email, body.password)
    _start_session(request, response, secret)
    return LoginOut(name=name, role=role, token=secret)


@router.post("/logout")
def logout(request: Request, response: Response):
    auth_service.logout(_secret(request))
    response.delete_cookie(COOKIE, path="/", samesite=config.COOKIE_SAMESITE,
                           secure=config.COOKIE_SAMESITE == "none" or None)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(request: Request):
    who = auth_service.verify_session(_secret(request))
    if not who:
        raise _unauth()
    return UserOut(name=who[1], role=who[2])
