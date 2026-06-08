# Bolão Copa 2026 ⚽

A mobile-first **World Cup 2026 prediction pool** (*bolão*). Friends predict the
score of every match, earn points by how close they get, and climb a live
ranking that updates as results come in. Server-rendered Django, dark-navy/gold
UI, Brazilian-Portuguese interface.

> **Status:** built and ready for the 2026 tournament. Fixtures and live results
> are sourced automatically from the official FIFA match-centre feed.

---

## Table of contents

- [Features](#features)
- [How scoring works](#how-scoring-works)
- [Tech stack](#tech-stack)
- [Architecture](#architecture)
- [Project structure](#project-structure)
- [Getting started (local)](#getting-started-local)
- [Configuration](#configuration)
- [Management commands](#management-commands)
- [Running with Docker](#running-with-docker)
- [Deployment (Railway)](#deployment-railway)
- [Testing](#testing)
- [Regenerating the CSS](#regenerating-the-css)
- [License](#license)

---

## Features

- **Score predictions** for every match of the current round, locked **30 minutes
  before kickoff**.
- **Automatic scoring** — results are fetched from FIFA and points are awarded the
  moment a match is decided. No manual data entry.
- **Live general ranking** with a deterministic tiebreak chain (points → exact
  hits → winner hits → fewer skips).
- **Per-round winners** — the platform highlights who won each round.
- **History** — every user's past predictions and points, including matches they
  skipped ("Não palpitou").
- **Invite-only** — no public sign-up; accounts are created by an admin. Sessions
  last a year (sliding).
- **Hardened by default** — per-user/per-IP rate limiting, validated external
  data, HTTPS/HSTS/secure-cookie switches for production.
- **Runs on a shoebox** — single SQLite file, single container, no Redis, no
  build pipeline. Designed for a Railway Hobby plan.

## How scoring works

Points are awarded per match by comparing the prediction to the final result
(extra time counts; penalty shootouts do **not** — a 1×1 decided on penalties
scores as a draw):

| Outcome | Points |
|---|---:|
| Exact score | **10** |
| Correct draw (wrong exact score) | **5** |
| Right winner **and** right goal difference | **7** |
| Right winner only | **5** |
| Wrong | **0** |
| No prediction (skipped) | **0** (no penalty) |

A **round** is the set of matches sharing the same round label (e.g. group
matchday 1, "Round of 16"). The ranking accumulates over **closed rounds only**
and is recomputed once when a round closes, then read from a stored snapshot —
pages never aggregate predictions on a request.

## Tech stack

- **Python 3.12+ / Django 6** — server-rendered templates, no SPA, no DRF.
- **SQLite** in both development and production (Railway volume), WAL mode.
- **Tailwind CSS v3** — pre-built and committed; no runtime or CI build step.
- **Gunicorn + WhiteNoise** for production serving.
- **requests** for the FIFA HTTP client.
- **pytest + pytest-django** for tests.
- **Data source:** [`api.fifa.com`](https://api.fifa.com/api/v3) v3 (`calendar/matches`)
  — free, no API key. One request returns the whole tournament (all 104 matches
  plus the knockout bracket).

## Architecture

The app is intentionally small and reads from the local DB on every page. The
FIFA API is **never** touched in a request path.

| Area | Module | Responsibility |
|---|---|---|
| Data model | `pool/models.py` | `Team`, `Match`, `Prediction`, `RankingEntry`, `RoundWinner`. `Match.save()` triggers scoring when goals change. |
| Scoring rules | `pool/utils/scoring.py` | Frozen point/winner formulas (the table above). |
| Rounds | `pool/services/rounds.py` | Round semantics; derives matchdays; tracks the current round. |
| Scoring pipeline | `pool/services/scoring_service.py` | Idempotent `score_match`, round closing, `RoundWinner` upsert. |
| Ranking | `pool/services/ranking.py` | Computes the ranking when a round closes and persists `RankingEntry` rows. |
| Rate limiting | `pool/services/throttle.py` | Fixed-window limiter on Django's LocMem cache (no Redis). |
| FIFA client | `pool/services/fifa_api.py` | Thin HTTP client; **normalizes/validates every field** from the undocumented feed; no DB writes. |
| Fixtures | `pool/services/fixtures.py` | The only place normalized matches become `Team`/`Match` rows. |

**Request economy (hard rules):**

- Pages read only the local DB.
- `check_results` is a cheap no-op (zero API calls) unless a match is past its
  expected end time. Run it every ~10 minutes.
- When anything is due, a single `calendar/matches` request covers every due
  match and resolves knockout placeholders as the bracket fills.
- Scored matches are never re-fetched or re-scored.

## Project structure

```
worldcup26/            Django project (settings, urls, wsgi/asgi)
pool/
├── models.py          Domain models + scoring trigger
├── views.py           matches / ranking / historic / login / save_prediction
├── urls.py
├── admin.py           account & data management (also wraps admin login throttle)
├── utils/scoring.py   frozen scoring formulas
├── services/          fifa_api, fixtures, rounds, scoring_service, ranking, throttle
├── management/commands/
│   ├── seed_world_cup.py   one-off pre-launch import (teams + 104 fixtures)
│   ├── check_results.py    result fetch + scoring (run on a schedule)
│   └── backup_db.py        rotated SQLite backup
├── templates/pool/    base, login, matches, ranking, historic
├── templatetags/      template helpers
├── static/pool/       committed, pre-built tailwind.css
└── tests/             pytest suite
Dockerfile, docker-compose.yml, start.sh   container + Railway setup
```

## Getting started (local)

**Prerequisites:** Python 3.12+ and `pip`.

```bash
# 1. Clone
git clone <your-fork-url> world-cup-26
cd world-cup-26

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 3. Dependencies
pip install -r requirements.txt

# 4. Database
python manage.py migrate

# 5. Import teams and the full fixture list (one-off)
python manage.py seed_world_cup

# 6. Create an admin account (accounts are invite-only)
python manage.py createsuperuser

# 7. Run
python manage.py runserver
```

Open <http://127.0.0.1:8000/>. Player accounts are created from the Django admin
at <http://127.0.0.1:8000/admin/> — there is no public registration.

To pull results during the tournament, run the scheduler command (see below) on a
timer, or use the Docker setup which runs it automatically.

## Configuration

All configuration is via environment variables (dev defaults are safe for local
use; set real values in production).

| Variable | Default | Notes |
|---|---|---|
| `SECRET_KEY` | dev fallback | **Required** in production. With `DEBUG=False`, the app refuses to boot on the fallback key. |
| `DEBUG` | `False` | `True` for local development. |
| `ALLOWED_HOSTS` | — | Comma-separated; required when `DEBUG=False`. |
| `CSRF_TRUSTED_ORIGINS` | — | Comma-separated origins for production. |
| `SQLITE_PATH` | `BASE_DIR/db.sqlite3` | Point at the mounted volume in production (e.g. `/data/db.sqlite3`). |
| `HTTPS_ONLY` | `False` | `True` in production: SSL redirect + secure cookies + HSTS. |
| `PORT` | `8000` | Honored by the container entrypoint (injected by the host). |
| `FIFA_API_BASE_URL` | `https://api.fifa.com/api/v3` | No API key required. |
| `FIFA_COMPETITION_ID` / `FIFA_SEASON_ID` | `17` / `285023` | World Cup 2026 identifiers. |
| `FIFA_FINISHED_STATUSES` | `0` | Comma-separated `MatchStatus` codes meaning "finished". |

Create a local `.env` (it is gitignored) for development overrides.

## Management commands

```bash
python manage.py seed_world_cup     # one-off: import all teams + 104 fixtures (idempotent)
python manage.py check_results      # fetch results + score due matches (run every ~10 min)
python manage.py backup_db          # rotated SQLite backup (keeps 3)
python manage.py createsuperuser    # create an account (invite-only model)
```

`check_results` is the heartbeat of the live tournament: cheap and API-free
unless a match has finished, in which case a single request scores everything
that is due and advances the bracket.

## Running with Docker

```bash
# Development: runserver, DEBUG on, code mounted from the host
docker compose up web

# Railway simulation: gunicorn + WhiteNoise, DEBUG off, migrations on boot,
# SQLite on a named volume (mirrors a Railway volume mount at /data)
docker compose --profile railway up --build railway
```

Both serve on <http://localhost:8000>.

## Deployment (Railway)

The app runs as a **single container** — there is no separate cron service,
because a Railway volume mounts on only one service and the SQLite file must be
reachable from the web process.

`start.sh` (the container entrypoint) does, in order:

1. `migrate`
2. background loop: `check_results` every 10 minutes
3. background loop: daily `backup_db` (rotated, 3 deep) + `clearsessions`
4. `gunicorn` as PID 1 (`--workers 1 --threads 4 --timeout 60`)

A single worker keeps the in-memory rate limiter exact; threads provide
concurrency. SQLite runs in WAL mode with a 20s lock timeout so the background
writers don't block page reads.

For a Railway deployment:

1. Create a service from this repo (it builds the `Dockerfile`).
2. Add a **volume** mounted at `/data`.
3. Set environment variables: `SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`,
   `CSRF_TRUSTED_ORIGINS`, `HTTPS_ONLY=True`, `SQLITE_PATH=/data/db.sqlite3`.
4. After the first deploy, run `seed_world_cup` and `createsuperuser` once
   (e.g. from a Railway shell).

## Testing

```bash
pytest                 # full suite
pytest --cov=pool      # with coverage
```

## Regenerating the CSS

The UI uses a pre-built, committed stylesheet at `pool/static/pool/tailwind.css`
— there is no runtime or CI build step. Regenerate it only when template classes
change, using the standalone Tailwind v3 CLI:

```bash
# https://github.com/tailwindlabs/tailwindcss/releases
tailwindcss -c tailwind.config.js -o pool/static/pool/tailwind.css --minify
```

## License

[MIT](LICENSE) © 2026 Marcos Santos
