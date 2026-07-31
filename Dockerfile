# Root-level image so hosts that expect a Dockerfile at the repo root
# (Hugging Face Spaces, Railway, Fly) can build without extra configuration.
# backend/Dockerfile is the same build with backend/ as its context.
#
# The Playwright base image ships Chromium plus every system library it needs,
# which is the fiddly part of running a browser-operating agent in a container.
# This tag must match the playwright pin in backend/requirements.txt.
FROM mcr.microsoft.com/playwright/python:v1.61.0-noble

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    BROWSER_HEADLESS=true \
    DATABASE_URL=sqlite+aiosqlite:////tmp/sentinel.db \
    PORT=7860

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY backend/app ./app

# Run as the image's non-root user so Chromium keeps its sandbox. The database
# lives in /tmp, which stays writable for this user; container storage is
# ephemeral on every host below, so treat the audit trail as per-deploy.
USER pwuser

EXPOSE 7860

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
