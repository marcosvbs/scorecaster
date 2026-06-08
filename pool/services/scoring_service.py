"""Match scoring and phase closing (spec sections 6, 7 and 9).

All entry points are idempotent: points are recomputed from scratch and the
phase winners are upserted, so re-running (API retry, admin correction) never
double-counts.
"""

import logging

from django.db.models import Count, Q, Sum

from pool.models import Match, Prediction, PhaseWinner
from pool.services.ranking import compute_ranking, rebuild_ranking_snapshot
from pool.utils.scoring import calculate_points

logger = logging.getLogger(__name__)


def score_match(match):
    """Score every prediction of a finished match and try to close its phase.

    Recomputes from match.home_goals/away_goals (idempotent), marks the match
    scored — it is never queried on the API again — and closes the phase when
    this was its last pending match.
    """
    predictions = list(Prediction.objects.filter(match=match))
    for p in predictions:
        p.points, p.result = calculate_points(
            p.home_goals, p.away_goals, match.home_goals, match.away_goals
        )
    Prediction.objects.bulk_update(predictions, ["points", "result"])

    # queryset update avoids re-entering Match.save()
    Match.objects.filter(pk=match.pk).update(is_scored=True)
    match.is_scored = True

    close_phase_if_complete(match.phase)

    # Live ranking: the snapshot moves on every scored match, not only when a
    # phase closes. One rebuild here covers the phase-close path too, since
    # close_phase_if_complete is only ever reached from score_match.
    rebuild_ranking_snapshot()


def close_phase_if_complete(phase_str):
    """Upsert PhaseWinner rows once every match of the phase is scored."""
    matches = Match.objects.filter(phase=phase_str)
    if not matches.exists() or matches.filter(is_scored=False).exists():
        return None

    winners = compute_phase_winners(phase_str)
    rows = []
    for winner in winners:
        row, _ = PhaseWinner.objects.update_or_create(
            phase=phase_str,
            user=winner.user,
            defaults={
                "points": winner.points,
                "exact_count": winner.exact_count,
                "partial_count": winner.partial_count,
            },
        )
        rows.append(row)

    # Drop stale rows from a previous computation (e.g. admin correction
    # changed the winner).
    PhaseWinner.objects.filter(phase=phase_str).exclude(
        user__in=[w.user for w in winners]
    ).delete()

    logger.info(
        "Phase %r closed, winner(s): %s",
        phase_str,
        ", ".join(w.user.username for w in winners) or "none",
    )
    return rows


def compute_phase_winners(phase_str):
    """Winner(s) of a phase among users who predicted in it (spec section 7).

    Tiebreak chain: phase points, then the general-ranking criteria (total
    points, exact hits, winner hits, fewer skips). Users still tied on every
    criterion are all winners — which, in practice, only happens when nobody
    scored (spec 7.4).
    """
    phase_stats = list(
        Prediction.objects.filter(match__phase=phase_str, match__is_scored=True)
        .values("user_id")
        .annotate(
            phase_points=Sum("points"),
            exact_count=Count("id", filter=Q(result="exact")),
            partial_count=Count("id", filter=Q(result="partial")),
        )
    )
    if not phase_stats:
        return []

    max_points = max(s["phase_points"] or 0 for s in phase_stats)
    candidates = {
        s["user_id"]: s for s in phase_stats if (s["phase_points"] or 0) == max_points
    }

    ranking_rows = [r for r in compute_ranking() if r.user.id in candidates]
    best_key = min(
        (-r.total_points, -r.exact_count, -r.winner_hit_count, r.skipped)
        for r in ranking_rows
    )
    winners = []
    for row in ranking_rows:
        key = (-row.total_points, -row.exact_count, -row.winner_hit_count, row.skipped)
        if key != best_key:
            continue
        stats = candidates[row.user.id]
        row.points = stats["phase_points"] or 0
        row.exact_count = stats["exact_count"]
        row.partial_count = stats["partial_count"]
        winners.append(row)
    return winners
