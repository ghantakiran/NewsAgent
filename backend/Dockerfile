# Runtime image for the NewsAgent API.
#
# Build context is the repository root, not backend/, because the API imports
# the shared catalyst engine from src/:
#   docker build -f backend/Dockerfile -t newsagent-api .
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# Dependencies first so code edits don't invalidate the layer.
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# src/ carries the catalyst engine that backend/services/catalyst_service.py
# imports. Without it the app raises ModuleNotFoundError on startup.
COPY config/ ./config/
COPY src/ ./src/
COPY backend/ ./backend/

RUN mkdir -p data

EXPOSE 8000

# Honour the platform's $PORT (Railway, Render, Fly all inject one).
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
