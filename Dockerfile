# syntax=docker/dockerfile:1.7

# ---- build stage: resolve and install runtime deps from the lockfile ----
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---- runtime stage: no uv, no dev deps, non-root ----
FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000
RUN groupadd --system app && useradd --system --gid app --no-create-home app
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root alembic ./alembic
COPY --chown=root:root app ./app
COPY --chown=root:root scripts ./scripts
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/health', timeout=2)" || exit 1
CMD ["sh", "scripts/start.sh"]
