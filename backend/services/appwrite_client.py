"""Thin factory helpers around the Appwrite Python SDK."""
from appwrite.client import Client
from appwrite.services.account import Account
from appwrite.services.storage import Storage
from appwrite.services.tables_db import TablesDB
from appwrite.services.users import Users

from backend import config
from backend.errors import AppError


def _base() -> Client:
    if not config.appwrite_configured():
        raise AppError(503, "The server is not connected to Appwrite yet. "
                            "Set APPWRITE_PROJECT_ID and APPWRITE_API_KEY (see .env.example).",
                       code="appwrite_not_configured")
    return (Client().set_endpoint(config.APPWRITE_ENDPOINT).set_project(config.APPWRITE_PROJECT_ID))


def admin_client() -> Client:
    """Client authenticated with the server API key (full backend access)."""
    return _base().set_key(config.APPWRITE_API_KEY)


def session_client(secret: str) -> Client:
    """Client acting as one logged-in user (their Appwrite session secret)."""
    return _base().set_session(secret)


def admin_account() -> Account:
    return Account(admin_client())


def users() -> Users:
    return Users(admin_client())


def db() -> TablesDB:
    return TablesDB(admin_client())


def storage() -> Storage:
    return Storage(admin_client())
