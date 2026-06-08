#!/bin/sh
# Container entrypoint: web server + result-check scheduler in ONE container.
# Railway volumes mount on a single service, so the SQLite database is only
# reachable from here — a separate cron service would not see it.
set -e

python manage.py migrate --noinput

# Low-frequency scheduler (spec section 9). Each tick is a cheap no-op with
# zero API calls unless a match is past its expected end. The subshell dies
# with the container; a failed tick never kills the loop.
(
  while true; do
    sleep 600
    python manage.py check_results || echo "check_results failed; retrying next tick" >&2
  done
) &

# Daily housekeeping: rotated SQLite backup (keeps 3 copies on the volume)
# and expired-session cleanup (1-year sliding sessions accumulate otherwise).
# A failed run never kills the loop.
(
  while true; do
    python manage.py backup_db || echo "backup_db failed; retrying tomorrow" >&2
    python manage.py clearsessions || echo "clearsessions failed; retrying tomorrow" >&2
    sleep 86400
  done
) &

# exec keeps gunicorn as PID 1 so it receives container signals directly.
# 1 worker keeps the LocMem throttle exact; threads stop a slow request from
# blocking everyone else.
exec gunicorn worldcup26.wsgi:application \
  --bind 0.0.0.0:"${PORT:-8000}" \
  --workers 1 --threads 4 --timeout 60
