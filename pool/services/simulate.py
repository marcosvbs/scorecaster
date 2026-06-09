"""Admin test helper: play out the first phase with random results.

Fills the first phase's matches with random goals and scores them through the
normal ``Match.save()`` pipeline (so scoring, ranking and phase-close cascade
exactly as in production). Reversible via the full-reset routine. Intended only
for pre-launch testing of the live flow — never wired into any scheduled task.
"""

import random

from django.db import transaction

from pool.models import Match


@transaction.atomic
def simulate_first_phase():
    """Score the first (chronologically earliest) phase with random goals.

    The first phase is the one the earliest match belongs to (e.g.
    "Group Stage - 1"), regardless of what is already scored. Each unscored
    match gets random goals (0–5) and is saved, triggering ``Match.save()`` →
    ``score_match`` (sets ``is_scored``, scores predictions, updates ranking,
    closes the phase). Already-scored matches are skipped — never re-scored.

    Returns a dict ``{phase, scored, skipped}`` for the confirmation message.
    """
    first = Match.objects.order_by("starts_at").first()
    if first is None:
        return {"phase": None, "scored": 0, "skipped": 0}

    phase = first.phase
    scored = skipped = 0
    for match in Match.objects.filter(phase=phase).order_by("starts_at"):
        if match.is_scored:
            skipped += 1
            continue
        match.home_goals = random.randint(0, 5)
        match.away_goals = random.randint(0, 5)
        match.save()  # triggers score_match via Match.save()
        scored += 1

    return {"phase": phase, "scored": scored, "skipped": skipped}
