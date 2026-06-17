"""OFFLINE generator for the in-app static demo.

Renders the three real pages (Jogos / Ranking / Histórico) against an
ISOLATED throwaway database seeded with fake data, then writes the HTML to
``pool/static/pool/demo/`` where WhiteNoise serves it as plain static files.
At runtime Railway does zero extra work — no view, no DB, no auth, no POST.

Hard guarantees baked into this command:
  * It NEVER touches the real database. Before any query it repoints
    ``DATABASES['default']['NAME']`` at a fresh temp file and refuses to run if
    that name resolves to the repo db or the SQLITE_PATH volume.
  * It is LOCAL-ONLY (run in dev, commit the output). It is never wired into
    start.sh / the Docker image.
  * Must run with DEBUG=True so ``{% static %}`` emits stable UNHASHED
    ``/static/...`` URLs (the committed HTML is served verbatim, so hashed
    manifest names would go stale on the next CSS rebuild).

Usage: python manage.py render_demo
"""

import json
import os
import tempfile

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.test import RequestFactory
from django.utils import timezone

PHASE_1 = "Group Stage - 1"
PHASE_2 = "Group Stage - 2"

VIEWER = "Marcos"
# Display order roughly best → worst (see EXACT_EVERY). The viewer sits 2nd so
# the highlighted "Você" row is visibly mid-pack, not an obvious winner.
ALL_USERS = ["Rafael", "Marcos", "Marina", "Bruno", "Carla", "Diego"]

# Lower divisor → more exact hits → higher rank. Spreads users out so the
# ranking and the Phase 1 winner are unambiguous.
EXACT_EVERY = {"Rafael": 2, "Marcos": 3, "Marina": 4, "Bruno": 5, "Carla": 6, "Diego": 7}

# Chronological offset of each phase from now(), in hours (matches within a
# phase are spaced 2h apart). PHASE_2 is scheduled separately to produce a mix
# of finished/live/locked/predicted/open cards on the Jogos page.
PHASE_OFFSET_HOURS = {
    "Group Stage - 1": -24 * 4,
    "Group Stage - 3": 24 * 4,
    "Round of 32": 24 * 7,
    "Round of 16": 24 * 10,
    "Quarter-final": 24 * 13,
    "Semi-final": 24 * 16,
    "Play-off for third place": 24 * 18,
    "Final": 24 * 19,
}
_FALLBACK_OFFSET_HOURS = 24 * 25

OUT_DIR = settings.BASE_DIR / "pool" / "static" / "pool" / "demo"


def _actual_score(index):
    """Deterministic but varied result for the index-th match."""
    return index % 3, (index * 2) % 4


def _prediction_for(home, away, level):
    """Derive a prediction from a base score at a given error level.

    0 = exact, 1 = right winner & goal difference, 2 = right winner only,
    3 = wrong. Point values are assigned by the real scoring pipeline.
    """
    if level == 0:
        return home, away
    if level == 1:  # shift both: keeps winner and goal difference (and draws)
        return home + 1, away + 1
    if level == 2:  # keep winner, change the margin
        if home > away:
            return home + 2, away
        if away > home:
            return home, away + 2
        return home + 1, away
    # level 3: flip it
    if home == away:
        return home + 1, away
    return away, home


class Command(BaseCommand):
    help = "Render the static in-app demo into pool/static/pool/demo/ (offline)."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "render_demo must run with DEBUG=True so static URLs stay "
                "unhashed. Run it locally in dev."
            )

        # ── Isolate the database (mandatory safety guard) ──────────────────
        conn = connections["default"]
        real_name = str(conn.settings_dict.get("NAME"))
        repo_db = str(settings.BASE_DIR / "db.sqlite3")
        volume_db = os.environ.get("SQLITE_PATH")

        tmp_dir = tempfile.mkdtemp(prefix="wc26_demo_")
        demo_db = os.path.join(tmp_dir, "demo.sqlite3")
        forbidden = {real_name, repo_db, volume_db, str(settings.DATABASES["default"]["NAME"])}
        if demo_db in forbidden:  # paranoia — a unique temp path never collides
            raise CommandError("Refusing to run: demo DB path collides with a real DB.")

        conn.close()
        conn.settings_dict["NAME"] = demo_db
        settings.DATABASES["default"]["NAME"] = demo_db
        if conn.settings_dict["NAME"] in forbidden:
            raise CommandError("DB isolation failed — aborting before any write.")

        try:
            call_command("migrate", verbosity=0, run_syncdb=True)
            self._seed()
            self._render()
        finally:
            conn.close()
            for suffix in ("", "-wal", "-shm"):
                try:
                    os.remove(demo_db + suffix)
                except OSError:
                    pass
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # ── Seeding (throwaway DB only) ────────────────────────────────────────

    def _seed(self):
        from django.contrib.auth.models import User
        from pool.models import Match, Prediction
        from pool.services.reset import full_reset

        call_command("loaddata", "demo_base", verbosity=0)
        full_reset()

        now = timezone.now()
        self._shift_dates(now)

        users = []
        for username in ALL_USERS:
            user, _ = User.objects.get_or_create(username=username)
            users.append(user)
        self._viewer = next(u for u in users if u.username == VIEWER)

        self._make_predictions(users)
        self._score()

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo DB: {len(users)} users, Phase 1 + 2 partial scored."
            )
        )

    def _shift_dates(self, now):
        from pool.models import Match

        td = timezone.timedelta
        for phase in Match.objects.values_list("phase", flat=True).distinct():
            matches = list(Match.objects.filter(phase=phase).order_by("starts_at", "id"))
            if phase == PHASE_2:
                for i, m in enumerate(matches):
                    m.starts_at = now + td(hours=self._phase2_offset_hours(i))
            else:
                base = PHASE_OFFSET_HOURS.get(phase, _FALLBACK_OFFSET_HOURS)
                for i, m in enumerate(matches):
                    m.starts_at = now + td(hours=base + i * 2)
            Match.objects.bulk_update(matches, ["starts_at"])

    @staticmethod
    def _phase2_offset_hours(i):
        # 0,1 finished (past, scored) · 2,3 live (just kicked off) ·
        # 4,5 locked (deadline passed, kickoff soon) · 6,7,8 predicted (future,
        # viewer predicted) · 9+ open (future, no prediction).
        if i in (0, 1):
            return -30 + i * 2
        if i in (2, 3):
            return -1 + (i - 2) * 0.5
        if i in (4, 5):
            return (15 + (i - 4) * 10) / 60  # +15min / +25min → locked
        return 30 + (i - 6) * 2

    def _make_predictions(self, users):
        from pool.models import Match, Prediction

        p1 = list(Match.objects.filter(phase=PHASE_1).order_by("starts_at", "id"))
        p2 = list(Match.objects.filter(phase=PHASE_2).order_by("starts_at", "id"))
        new = []

        # Phase 1 — everyone (a couple of skips per user → "Não palpitou").
        for u_idx, user in enumerate(users):
            every = EXACT_EVERY[user.username]
            for m_idx, match in enumerate(p1):
                if (u_idx * 5 + m_idx * 7) % 17 == 0:
                    continue
                home, away = _actual_score(m_idx)
                level = 0 if m_idx % every == 0 else (m_idx % 3) + 1
                ph, pa = _prediction_for(home, away, level)
                new.append(Prediction(user=user, match=match, home_goals=ph, away_goals=pa))

        # Phase 2 idx 0-5 (finished/live/locked) — everyone predicts so the
        # "Outros palpites" modal has data on those revealed cards.
        for u_idx, user in enumerate(users):
            every = EXACT_EVERY[user.username]
            for m_idx in range(0, min(6, len(p2))):
                base_h, base_a = _actual_score(m_idx)
                level = 0 if (m_idx + u_idx) % every == 0 else ((m_idx + u_idx) % 3) + 1
                ph, pa = _prediction_for(base_h, base_a, level)
                new.append(Prediction(user=user, match=p2[m_idx], home_goals=ph, away_goals=pa))

        # Phase 2 idx 6-8 — only the viewer, so those future cards show as
        # "Palpitado" while the rest stay "Palpitar" (open).
        for m_idx in range(6, min(9, len(p2))):
            new.append(Prediction(user=self._viewer, match=p2[m_idx], home_goals=2, away_goals=1))

        Prediction.objects.bulk_create(new)

    def _score(self):
        from pool.models import Match

        # Saving goals fires Match.save() → score_match (scores predictions,
        # closes a fully-scored phase, rebuilds the ranking snapshot).
        for m_idx, match in enumerate(
            Match.objects.filter(phase=PHASE_1).order_by("starts_at", "id")
        ):
            match.home_goals, match.away_goals = _actual_score(m_idx)
            match.save()

        p2 = list(Match.objects.filter(phase=PHASE_2).order_by("starts_at", "id"))
        for m_idx in range(0, min(2, len(p2))):  # only the two "finished" cards
            match = p2[m_idx]
            match.home_goals, match.away_goals = _actual_score(m_idx)
            match.save()

    # ── Build the inlined "Outros palpites" data ───────────────────────────

    def _build_others(self, now):
        """Mirror views.match_predictions for every revealed match."""
        from pool.models import Match, Prediction

        data = {}
        matches = Match.objects.select_related("home_team", "away_team").all()
        for match in matches:
            if not (match.is_scored or now >= match.prediction_deadline):
                continue
            preds = Prediction.objects.filter(match=match).select_related("user")
            preds = preds.order_by(
                *(("-points", "user__username") if match.is_scored else ("user__username",))
            )
            viewer_row = None
            others = []
            for p in preds:
                row = {
                    "username": p.user.username,
                    "home_goals": p.home_goals,
                    "away_goals": p.away_goals,
                    "result": p.result if match.is_scored else None,
                    "points": p.points if match.is_scored else None,
                }
                if p.user_id == self._viewer.id:
                    row["predicted"] = True
                    viewer_row = row
                else:
                    others.append(row)
            if viewer_row is None:
                viewer_row = {
                    "username": self._viewer.username,
                    "predicted": False,
                    "home_goals": None,
                    "away_goals": None,
                    "result": None,
                    "points": None,
                }
            data[str(match.id)] = {
                "ok": True,
                "is_finished": match.is_scored,
                "viewer": viewer_row,
                "predictions": others,
            }
        return data

    # ── Render the three pages to static HTML ──────────────────────────────

    def _render(self):
        from pool import views

        now = timezone.now()
        others_json = json.dumps(self._build_others(now))

        rf = RequestFactory()
        pages = [
            ("index.html", views.matches, "/"),
            ("ranking.html", views.ranking, "/ranking/"),
            ("historico.html", views.historic, "/historic/"),
        ]
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for fname, view, path in pages:
            request = rf.get(path)
            request.user = self._viewer
            request.is_demo = True
            request.demo_others_json = others_json
            response = view(request)
            if hasattr(response, "render"):
                response.render()
            (OUT_DIR / fname).write_bytes(response.content)
            self.stdout.write(f"Wrote {OUT_DIR / fname}")
