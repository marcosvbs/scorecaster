#!/bin/sh
# Container entrypoint: web server + result-check scheduler in ONE container.
# Railway volumes mount on a single service, so the SQLite database is only
# reachable from here — a separate cron service would not see it.
set -e

python manage.py migrate --noinput

# Event-driven scheduler (spec section 9). check_results scores due matches and
# resolves bracket placeholders, then prints (on stdout) the seconds to sleep
# before the next run: the time until the next match's expected end, 1h while a
# phase still has placeholder teams, capped at a few hours when idle. So between
# phases the loop wakes a handful of times a day, not every 10 min. Logs go to
# stderr; stdout carries only the delay integer. A failed run (empty/non-numeric
# output, non-zero exit) falls back to 600s and never kills the loop. The
# subshell dies with the container.
(
  while true; do
    delay=$(python manage.py check_results --print-delay | tail -n1)
    case "$delay" in
      ''|*[!0-9]*) delay=600 ;;
    esac
    sleep "$delay"
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
