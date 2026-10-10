FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.12.24 /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts/container_smoke.py ./scripts/container_smoke.py
COPY scripts/ingestion_smoke.py ./scripts/ingestion_smoke.py
RUN uv sync --frozen --no-dev --no-editable && useradd --uid 10001 --create-home zoclip \
    && mkdir -p /app/var/mailbox /app/var/media && chown -R zoclip:zoclip /app/var
ENV PATH="/opt/venv/bin:$PATH"
USER 10001:10001
CMD ["uvicorn", "zoclip.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--limit-concurrency", "32", "--no-access-log", "--no-proxy-headers"]
