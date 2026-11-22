"""Application errors carrying a user-friendly message and an HTTP status."""


class AppError(Exception):
    def __init__(self, status_code: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code  # machine-readable hint, e.g. "slot_occupied"
