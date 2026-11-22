"""Faculty authentication backed by Appwrite Auth (email + password).

Login creates a real Appwrite session; its secret lives in an httpOnly cookie. Each request
re-validates that session with Appwrite (cached for a few seconds). Only users carrying the
``faculty`` label may use the app, so open sign-ups in Appwrite can never grant access.
"""
import hashlib
import logging
import threading
import time

from appwrite.exception import AppwriteException
from appwrite.services.account import Account

from backend import config
from backend.errors import AppError
from backend.services import appwrite_client

log = logging.getLogger("cfg.auth")

CACHE_TTL = 30  # seconds a validated session is trusted before asking Appwrite again
_cache: dict[str, tuple[float, tuple[str, str]]] = {}
_cache_lock = threading.Lock()


def _ck(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _check_faculty(user: dict) -> tuple[str, str]:
    if config.FACULTY_LABEL not in (user.get("labels") or []):
        raise AppError(403, "This account is not authorised to use the Course File Generator.",
                       code="not_faculty")
    name = (user.get("name") or user.get("email") or "Faculty").strip()
    return user["$id"], name


def login(email: str, password: str) -> tuple[str, str, str]:
    """Return (session_secret, user_id, display_name) or raise AppError."""
    email, password = (email or "").strip(), password or ""
    if not email or not password:
        raise AppError(401, "Incorrect email or password.", code="bad_credentials")
    try:
        session = appwrite_client.admin_account().create_email_password_session(email, password)
        secret = session.secret
        user = Account(appwrite_client.session_client(secret)).get()
        user_id, name = _check_faculty(user if isinstance(user, dict) else user.to_dict())
    except AppError:
        _try_delete_session(locals().get("secret"))
        raise
    except AppwriteException as e:
        if e.code in (400, 401):
            raise AppError(401, "Incorrect email or password.", code="bad_credentials")
        if e.code == 429:
            raise AppError(429, "Too many attempts. Please wait a few minutes and try again.")
        log.exception("Appwrite login failed")
        raise AppError(502, "Could not reach the login service. Please try again.")
    with _cache_lock:
        _cache[_ck(secret)] = (time.time() + CACHE_TTL, (user_id, name))
    return secret, user_id, name


def _try_delete_session(secret: str | None) -> None:
    if not secret:
        return
    try:
        Account(appwrite_client.session_client(secret)).delete_session("current")
    except Exception:  # best effort
        pass


def verify_session(secret: str | None) -> tuple[str, str] | None:
    """Return (user_id, display_name) for a valid faculty session, else None."""
    if not secret:
        return None
    key = _ck(secret)
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        user = Account(appwrite_client.session_client(secret)).get()
        who = _check_faculty(user if isinstance(user, dict) else user.to_dict())
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
