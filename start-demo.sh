#!/bin/sh
# Demo entrypoint: frozen, offline mock snapshot (no api.fifa.com, no cron loops).
# The DB is ephemeral — seed_demo rebuilds the whole snapshot on every boot, so
# the demo stays evergreen (Phase 1 in the recent past, Phase 2 upcoming) and a
# free-tier host needs no persistent volume.
set -e

python manage.py migrate --noinput
python manage.py seed_demo

# 1 worker keeps the LocMem throttle exact; threads give concurrency.
exec gunicorn worldcup26.wsgi:application \
  --bind 0.0.0.0:"${PORT:-8000}" \
  --workers 1 --threads 4 --timeout 60
