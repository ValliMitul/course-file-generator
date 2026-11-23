"""Input validation helpers."""
import string
import re
import uuid

from backend.errors import AppError

LETTERS = list(string.ascii_uppercase)  # A..Z, generated programmatically


def validate_letter(letter: str) -> str:
    letter = (letter or "").strip().upper()
    if len(letter) != 1 or letter not in LETTERS:
        raise AppError(400, "Invalid section. Use a single letter from A to Z.")
    return letter


_DEFAULT_ID = re.compile(r"^dflt[A-Z]_[A-Za-z0-9._-]{1,30}$")      # ids of the built-in default documents


def validate_file_id(file_id: str) -> str:
    if _DEFAULT_ID.match((file_id or "").strip()):
        return file_id.strip()
    try:
        return uuid.UUID(hex=(file_id or "").strip()).hex
    except (ValueError, AttributeError, TypeError):
        raise AppError(400, "Invalid file ID.")
