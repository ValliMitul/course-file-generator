"""Authentication and role-based access control on top of Appwrite Auth (email + password).

* Sign-in creates a real Appwrite session; its secret lives in an httpOnly cookie and is
  re-validated with Appwrite on requests (cached for a few seconds).
* Roles are the Appwrite user labels ``faculty`` and ``admin``. Sign-up always creates a
  *faculty* user; only an administrator (or the Appwrite console) can grant ``admin``.
"""
import hashlib
import logging
import re
import threading
import time

from appwrite.exception import AppwriteException
from appwrite.id import ID
from appwrite.query import Query
from appwrite.services.account import Account

from backend import config
from backend.errors import AppError
from backend.services import appwrite_client

log = logging.getLogger("cfg.auth")

CACHE_TTL = 30  # seconds a validated session is trusted before asking Appwrite again
_cache: dict[str, tuple[float, tuple[str, str, str]]] = {}
_cache_lock = threading.Lock()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _ck(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def role_of(labels) -> str | None:
    labels = labels or []
    if config.ADMIN_LABEL in labels:
        return "admin"
    if config.FACULTY_LABEL in labels:
        return "faculty"
    return None


def _check_access(user: dict) -> tuple[str, str, str]:
    role = role_of(user.get("labels"))
    if not role:
        raise AppError(403, "This account has no role assigned. Ask an administrator for access.", code="no_role")
    name = (user.get("name") or user.get("email") or "User").strip()
    return user["$id"], name, role


def _as_dict(user) -> dict:
    return user if isinstance(user, dict) else user.to_dict()


def login(email: str, password: str) -> tuple[str, str, str, str]:
    """Return (session_secret, user_id, display_name, role) or raise AppError."""
    email, password = (email or "").strip(), password or ""
    if not email or not password:
        raise AppError(401, "Incorrect email or password.", code="bad_credentials")
    secret = None
    try:
        session = appwrite_client.admin_account().create_email_password_session(email, password)
        secret = session.secret
        user = _as_dict(Account(appwrite_client.session_client(secret)).get())
        user_id, name, role = _check_access(user)
    except AppError:
        _try_delete_session(secret)
        raise
    except AppwriteException as e:
        if e.code in (400, 401):
            raise AppError(401, "Incorrect email or password.", code="bad_credentials")
        if e.code == 429:
            raise AppError(429, "Too many attempts. Please wait a few minutes and try again.")
        log.exception("Appwrite login failed")
        raise AppError(502, "Could not reach the login service. Please try again.")
    with _cache_lock:
        _cache[_ck(secret)] = (time.time() + CACHE_TTL, (user_id, name, role))
    return secret, user_id, name, role


def signup(name: str, email: str, password: str) -> tuple[str, str, str, str]:
    """Create a *faculty* account, then sign it in. Admin role can never be self-assigned."""
    name, email = " ".join((name or "").split()), (email or "").strip().lower()
    if len(name) < 2 or len(name) > 100:
        raise AppError(400, "Please enter your full name.")
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise AppError(400, "Please enter a valid email address.")
    if config.SIGNUP_DOMAINS and email.rsplit("@", 1)[1] not in config.SIGNUP_DOMAINS:
        raise AppError(403, "Sign-up is limited to these email domains: " + ", ".join(config.SIGNUP_DOMAINS) + ".",
                       code="domain_not_allowed")
    if len(password or "") < 8 or len(password) > 256:
        raise AppError(400, "The password must be at least 8 characters long.")
    users = appwrite_client.users()
    try:
        user = users.create(ID.unique(), email=email, password=password, name=name)
        users.update_labels(_as_dict(user)["$id"], [config.FACULTY_LABEL])
    except AppwriteException as e:
        if e.code == 409:
            raise AppError(409, "An account with this email already exists. Please sign in.", code="exists")
        if e.code == 400:
            raise AppError(400, "That email or password was rejected. Use a stronger password (8+ characters).")
        log.exception("Appwrite sign-up failed")
        raise AppError(502, "Could not create the account. Please try again.")
    return login(email, password)


def _try_delete_session(secret: str | None) -> None:
    if not secret:
        return
    try:
        Account(appwrite_client.session_client(secret)).delete_session("current")
    except Exception:  # best effort
        pass


def verify_session(secret: str | None) -> tuple[str, str, str] | None:
    """Return (user_id, display_name, role) for a valid session, else None."""
    if not secret:
        return None
    key = _ck(secret)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        who = _check_access(_as_dict(Account(appwrite_client.session_client(secret)).get()))
    except AppError:
        return None
    except AppwriteException as e:
        if e.code in (401, 403):
            with _cache_lock:
                _cache.pop(key, None)
            return None
        log.exception("Appwrite session check failed")
        raise AppError(502, "Could not reach the login service. Please try again.")
    with _cache_lock:
        if len(_cache) > 1000:
            _cache.clear()
        _cache[key] = (now + CACHE_TTL, who)
    return who


def logout(secret: str | None) -> None:
    if secret:
        with _cache_lock:
            _cache.pop(_ck(secret), None)
        _try_delete_session(secret)


def invalidate_all() -> None:
    with _cache_lock:
        _cache.clear()


# ----------------------------------------------------------- admin: users
def list_users() -> list[dict]:
    out, offset = [], 0
    while True:
        page = appwrite_client.users().list([Query.limit(100), Query.offset(offset), Query.order_desc("$createdAt")])
        batch = [_as_dict(u) for u in page.users]
        for u in batch:
            out.append({"id": u["$id"], "name": u.get("name") or "", "email": u.get("email") or "",
                        "role": role_of(u.get("labels")), "created": (u.get("$createdAt") or "")[:10]})
        if len(batch) < 100:
            return out
        offset += 100


def set_role(user_id: str, role: str, acting_user: str) -> dict:
    if role not in ("faculty", "admin"):
        raise AppError(400, "Role must be 'faculty' or 'admin'.")
    if user_id == acting_user and role != "admin":
        raise AppError(400, "You cannot remove your own admin role. Ask another administrator.")
    users = appwrite_client.users()
    try:
        user = _as_dict(users.get(user_id))
        labels = {l for l in (user.get("labels") or []) if l not in config.ROLES}
        labels.add(config.FACULTY_LABEL)                  # admins keep faculty rights
        if role == "admin":
            labels.add(config.ADMIN_LABEL)
        users.update_labels(user_id, sorted(labels))
    except AppwriteException as e:
        if e.code == 404:
            raise AppError(404, "User not found.")
        log.exception("set_role failed")
        raise AppError(502, "Could not update the role. Please try again.")
    invalidate_all()
    return {"id": user_id, "role": role}


# --------------------------------------------------- brute-force limiter
_failures: dict[str, list[float]] = {}
WINDOW, MAX_FAILS = 300, 10


def too_many_attempts(ip: str) -> bool:
    now = time.time()
    recent = [t for t in _failures.get(ip, []) if now - t < WINDOW]
    _failures[ip] = recent
    return len(recent) >= MAX_FAILS


def record_failure(ip: str) -> None:
    _failures.setdefault(ip, []).append(time.time())
