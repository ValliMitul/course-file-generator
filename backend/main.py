"""FastAPI entry point.

Run from the project root:
    uvicorn backend.main:app --host 127.0.0.1 --port 8000
Hosting: see Dockerfile (binds to $PORT).
"""
import logging

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend import config
from backend.api import auth, catalog, convert, generate, sections, upload
from backend.errors import AppError
from backend.models import HealthResponse
from backend.services import file_converter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cfg.main")

app = FastAPI(title="Course File Generator", version="1.0.0")

if config.ALLOWED_ORIGINS:
    app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type"])


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code,
                        content={"detail": exc.message, "code": exc.code})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    log.warning("Validation error: %s", exc.errors())
    return JSONResponse(status_code=422, content={"detail": "The request was invalid or incomplete.",
                                                  "code": "validation"})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    log.exception("Unhandled error", exc_info=exc)  # full traceback stays in the terminal
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. "
                                                           "Check the backend terminal for details."})


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
def health():
    lo = file_converter.libreoffice_status()
    lo["path"] = None   # health is public: don't reveal local paths
    return {"status": "ok", "appwrite_configured": config.appwrite_configured(), "libreoffice": lo}


app.include_router(auth.router)
protected = [Depends(auth.require_user)]   # everything below needs a logged-in faculty member
app.include_router(upload.router, dependencies=protected)
app.include_router(convert.router, dependencies=protected)
app.include_router(sections.router, dependencies=protected)
app.include_router(generate.router, dependencies=protected)
app.include_router(catalog.router, dependencies=protected)

# Serve the frontend too, so http://127.0.0.1:8000 works on its own (no second server needed).
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
