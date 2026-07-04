# Lean serving image for the classifier API.
# Single-stage is fine here: the deps are pure-Python wheels, so there's nothing
# to compile and a multi-stage build would add complexity without shrinking much.
FROM python:3.14-slim

# Don't write .pyc files; flush stdout/stderr immediately so logs show up in
# Cloud Run without buffering.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install serving deps first so this layer is cached unless the deps change.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Only the source the service needs. classify.py is imported by api.py; the
# generator/eval scripts and data are not part of the runtime image.
COPY src/api.py src/classify.py ./src/

# Run as a non-root user. Standard hardening: if the process is compromised it
# isn't root inside the container.
RUN useradd --create-home --uid 1000 appuser
USER appuser

# Cloud Run sends traffic to $PORT (defaults to 8080). Shell form so $PORT is
# expanded at runtime; fall back to 8080 for local `docker run`.
EXPOSE 8080
CMD uvicorn api:app --app-dir src --host 0.0.0.0 --port ${PORT:-8080}
