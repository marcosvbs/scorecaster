"""Seed a self-contained, evergreen DEMO snapshot — no api.fifa.com, no real users.

Loads the committed teams+fixtures fixture (offline), then builds a frozen
state "just after Phase 1": 5 fictional users with scored Group Stage - 1
predictions (varied accuracy → a real ranking and a phase winner), with Group
Stage - 2 left open as the current phase so the prediction UI is visible.

Dates are recomputed relative to now() on every run, so the demo always looks
live (Phase 1 in the recent past, Phase 2 upcoming) no matter when it boots.
Idempotent: re-running resets predictions/scores and rebuilds the same state.

Usage: python manage.py seed_demo
"""

import logging

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone

from pool.models import Match, Prediction
from pool.services.reset import full_reset

logger = logging.getLogger(__name__)

PHASE_1 = "Group Stage - 1"
PHASE_2 = "Group Stage - 2"

# Fictional competitors (display order roughly best → worst, see EXACT_EVERY).
DEMO_USERS = ["Rafael", "Marina", "Bruno", "Carla", "Diego"]
DEMO_PASSWORD = "demo"

# Chronological offset of each phase from now(), in hours. Reassigning every
# match relative to now() (instead of shifting real dates by a single delta)
# guarantees Phase 1 lands fully in the past and Phase 2 stays in the future
# regardless of the real schedule's inter-phase gaps. Matches within a phase
# are spaced 2h apart in their original order.
PHASE_OFFSET_HOURS = {
    "Group Stage - 1": -24 * 4,
    "Group Stage - 2": 36,
    "Group Stage - 3": 24 * 4,
    "Round of 32": 24 * 7,
    "Round of 16": 24 * 10,
    "Quarter-final": 24 * 13,
    "Semi-final": 24 * 16,
    "Play-off for third place": 24 * 18,
    "Final": 24 * 19,
}
_FALLBACK_OFFSET_HOURS = 24 * 25

# Lower divisor → more exact hits → higher rank. Spreads the 5 users out so the
# ranking and the Phase 1 winner are unambiguous.
EXACT_EVERY = {"Rafael": 2, "Marina": 3, "Bruno": 4, "Carla": 5, "Diego": 6}


def _actual_score(index):
    """Deterministic but varied result for the index-th Phase 1 match."""
    return index % 3, (index * 2) % 4


def _prediction_for(home, away, level):
    """Derive a prediction from the actual score at a given error level.

    0 = exact, 1 = right winner & goal difference, 2 = right winner only,
    3 = wrong. Exact point values are left for the scoring pipeline to assign.
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
        return home + 1, away  # draw → a home win (right "winner"? no, was draw)
    # level 3: flip it
    if home == away:
        return home + 1, away  # draw predicted as a home win
    return away, home  # swap → wrong winner


class Command(BaseCommand):
    help = "Seed a frozen, offline demo snapshot (5 users, Phase 1 scored)."

    @transaction.atomic
    def handle(self, *args, **options):
        if not Match.objects.exists():
            call_command("loaddata", "demo_base", verbosity=0)
            self.stdout.write("Loaded demo_base fixture.")

        # Clean slate (predictions, ranking, phase winners, match scores).
        full_reset()

        self._shift_dates()
        users = self._ensure_users()
        self._make_predictions(users)
        self._score_phase_1()

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready: {len(users)} users, Phase 1 scored, "
                f"current phase = {PHASE_2}."
            )
        )

    def _shift_dates(self):
        now = timezone.now()
        for phase in Match.objects.values_list("phase", flat=True).distinct():
            base = PHASE_OFFSET_HOURS.get(phase, _FALLBACK_OFFSET_HOURS)
            matches = list(
                Match.objects.filter(phase=phase).order_by("starts_at", "id")
            )
            for i, match in enumerate(matches):
                match.starts_at = now + timezone.timedelta(hours=base + i * 2)
            Match.objects.bulk_update(matches, ["starts_at"])

    def _ensure_users(self):
        users = []
        for username in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save(update_fields=["password"])
            users.append(user)
        return users

    def _make_predictions(self, users):
        phase_1 = list(Match.objects.filter(phase=PHASE_1).order_by("starts_at", "id"))
        phase_2 = list(Match.objects.filter(phase=PHASE_2).order_by("starts_at", "id"))

        new = []
        for u_idx, user in enumerate(users):
            every = EXACT_EVERY[DEMO_USERS[u_idx]]
            for m_idx, match in enumerate(phase_1):
                # ~1-2 skips per user, spread differently per user.
                if (u_idx * 5 + m_idx * 7) % 17 == 0:
                    continue
                home, away = _actual_score(m_idx)
                if m_idx % every == 0:
                    level = 0
                else:
                    level = (m_idx % 3) + 1  # 1, 2 or 3
                ph, pa = _prediction_for(home, away, level)
                new.append(
                    Prediction(
                        user=user, match=match, home_goals=ph, away_goals=pa
                    )
                )

            # A few open-phase predictions so the matches page shows the
            # "predicted" state next to still-open matches.
            for match in phase_2[: max(0, 3 - u_idx)]:
                new.append(
                    Prediction(user=user, match=match, home_goals=1, away_goals=0)
                )

        Prediction.objects.bulk_create(new)

    def _score_phase_1(self):
        # Saving goals fires Match.save() → score_match: scores predictions,
        # closes the phase (PhaseWinner), and rebuilds the ranking snapshot.
        for m_idx, match in enumerate(
            Match.objects.filter(phase=PHASE_1).order_by("starts_at", "id")
        ):
            match.home_goals, match.away_goals = _actual_score(m_idx)
            match.save()
