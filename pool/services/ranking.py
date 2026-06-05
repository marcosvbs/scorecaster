"""General ranking with tiebreakers (spec section 8).

Cumulative over closed rounds only: points from a round still in progress
never show up. Tiebreakers: total points, exact hits, winner hits
(result exact or partial), fewer skipped matches; username as a final
deterministic fallback.
"""

from types import SimpleNamespace

from django.contrib.auth.models import User
from django.db.models import Count, Q, Sum

from pool.models import Match, Prediction


def closed_rounds():
    """Rounds whose every match is scored."""
    all_rounds = set(Match.objects.values_list("round", flat=True).distinct())
    open_rounds = set(
        Match.objects.filter(is_scored=False).values_list("round", flat=True).distinct()
    )
    return all_rounds - open_rounds


def compute_ranking():
    closed = closed_rounds()
    scored_match_count = Match.objects.filter(round__in=closed, is_scored=True).count()

    stats_by_user = {
        row["user_id"]: row
        for row in (
            Prediction.objects.filter(match__round__in=closed, match__is_scored=True)
            .values("user_id")
            .annotate(
                total_points=Sum("points"),
                exact_count=Count("id", filter=Q(result="exact")),
                winner_hit_count=Count(
                    "id", filter=Q(result__in=["exact", "partial"])
                ),
                prediction_count=Count("id"),
            )
        )
    }

    rows = []
    for user in User.objects.all():
        stats = stats_by_user.get(user.id, {})
        prediction_count = stats.get("prediction_count", 0)
        rows.append(
            SimpleNamespace(
                user=user,
                total_points=stats.get("total_points") or 0,
                exact_count=stats.get("exact_count", 0),
                winner_hit_count=stats.get("winner_hit_count", 0),
                skipped=scored_match_count - prediction_count,
            )
        )

    rows.sort(
        key=lambda r: (
            -r.total_points,
            -r.exact_count,
            -r.winner_hit_count,
            r.skipped,
            r.user.username.lower(),
        )
    )
    for position, row in enumerate(rows, start=1):
        row.position = position
    return rows
