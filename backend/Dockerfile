# ---- AutoBI backend (FastAPI + DuckDB) -------------------------------------
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code.
COPY app ./app

# Uploaded datasets live here; mount a volume in production for persistence.
RUN mkdir -p /app/storage
ENV STORAGE_DIR=/app/storage

EXPOSE 8000

# A simple healthcheck so orchestrators know when the API is ready. It reads
# $PORT so it works both locally (8000) and on Render (its assigned port).
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import os,urllib.request,sys; p=os.environ.get('PORT','8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{p}/api/health').status==200 else 1)"

# Render (and most PaaS) inject a PORT env var the service must bind to; fall
# back to 8000 for local runs and docker-compose.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
