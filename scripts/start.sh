#!/bin/sh
# Container entrypoint. Optionally applies migrations and the idempotent seed
# before serving. Render's free tier has no pre-deploy command, so this is the
# release step there. Both operations are safe to repeat on every boot.
set -eu

if [ "${RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
    alembic upgrade head
fi
if [ "${RUN_SEED_ON_START:-false}" = "true" ]; then
    python -m scripts.seed
fi

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --proxy-headers \
    --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" \
    --no-access-log
