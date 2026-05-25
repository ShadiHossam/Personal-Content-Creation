FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# System deps that Playwright + cryptography + pdfplumber need on slim.
# `playwright install-deps` adds everything else (libnss3, libatk1.0-0, ...).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        libffi-dev \
        libssl-dev \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first for layer caching
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + Playwright system dependencies in one layer
RUN playwright install --with-deps chromium

COPY . .

# SQLite + scraper state live here; mount a volume to persist them.
RUN mkdir -p /app/data && chmod 700 /app/data

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
