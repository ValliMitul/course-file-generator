"""Input validation helpers."""
import string
import uuid

from backend.errors import AppError

LETTERS = list(string.ascii_uppercase)  # A..Z, generated programmatically


def validate_letter(letter: str) -> str:
    letter = (letter or "").strip().upper()
    if len(letter) != 1 or letter not in LETTERS:
        raise AppError(400, "Invalid section. Use a single letter from A to Z.")
    return letter


def validate_file_id(file_id: str) -> str:
    try:
        return uuid.UUID(hex=(file_id or "").strip()).hex
    except (ValueError, AttributeError, TypeError):
        raise AppError(400, "Invalid file ID.")
