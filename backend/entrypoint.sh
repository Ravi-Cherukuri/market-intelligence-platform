#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-0}" = "1" ]; then
  alembic upgrade head
  python -m app.seed
fi
exec "$@"
