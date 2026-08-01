# syntax=docker/dockerfile:1.25
FROM python:3.14-slim

# Build arguments
ARG APP_VERSION=dev
ARG BUILD_DATE=unknown
ARG BUILD_NUMBER=0

# OCI Image labels
LABEL org.opencontainers.image.source="https://github.com/stuartshay/otel-data-api"
LABEL org.opencontainers.image.description="FastAPI microservice for GPS data with PostGIS"
LABEL org.opencontainers.image.licenses="MIT"
LABEL org.opencontainers.image.version="${APP_VERSION}"
LABEL org.opencontainers.image.created="${BUILD_DATE}"
LABEL com.github.actions.build-number="${BUILD_NUMBER}"

# Python runtime hygiene
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Set working directory
WORKDIR /app

# Create non-root user up front so later COPY layers don't invalidate it
RUN useradd -r -u 1000 -m -d /home/appuser appuser

# Install dependencies first (layer caching + BuildKit pip cache mount)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    pip install -r requirements.txt

# Copy application code
COPY run.py .
COPY app/ ./app/

# Set version as environment variables for runtime access
ENV APP_VERSION=${APP_VERSION} \
    BUILD_DATE=${BUILD_DATE} \
    BUILD_NUMBER=${BUILD_NUMBER}

USER 1000

# Expose port
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

# Run with uvicorn (newrelic-admin wraps for APM when license key is set)
CMD ["newrelic-admin", "run-program", "uvicorn", "run:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
