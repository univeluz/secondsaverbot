# ---------- Base ----------
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /app

# ---------- System dependencies ----------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        nodejs \
        nodejs \
        fonts-roboto quickjs \
    && rm -rf /var/lib/apt/lists/*

# ---------- Poetry ----------
RUN pip install --no-cache-dir poetry

# Copy dependency files first for better Docker layer caching
COPY pyproject.toml poetry.lock ./

RUN poetry install --no-root --no-ansi

# ---------- Application ----------
COPY . /app

# ---------- Non-root user ----------
RUN adduser --uid 5678 --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

WORKDIR /app/src

CMD ["python", "main.py"]
