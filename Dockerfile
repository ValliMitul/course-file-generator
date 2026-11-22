# Course File Generator - container for any Docker host (Render, Railway, Fly.io, a VPS, ...).
# Needs LibreOffice for Word/Excel/PowerPoint -> PDF, so it cannot run on Appwrite Functions/Sites.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer libreoffice-calc libreoffice-impress \
        fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend backend
COPY frontend frontend

ENV PYTHONUNBUFFERED=1 HOME=/tmp
RUN useradd -m app && chown -R app /app
USER app

# Hosts inject $PORT; --proxy-headers lets the app see https behind the host's proxy.
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
