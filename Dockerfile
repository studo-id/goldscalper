# GoldScalper — application image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC

WORKDIR /app

# System deps (psql client for healthchecks, curl for probes)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl postgresql-client tzdata \
    && rm -rf /var/lib/apt/lists/*

# Python deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Non-root user
RUN useradd -m -u 1000 gs && chown -R gs:gs /app
USER gs

EXPOSE 9090

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:9090/health || exit 1

CMD ["python", "run.py"]
