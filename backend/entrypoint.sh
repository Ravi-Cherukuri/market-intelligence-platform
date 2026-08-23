#!/bin/sh
set -eu

if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  alembic upgrade head
  python -m app.seed
fi
exec "$@"
