"""General ranking with tiebreakers (spec section 8).

Cumulative over every scored match (live, per-match): points from a match
show up as soon as it is scored, even while its phase is still in progress.
Tiebreakers: total points, exact hits, winner hits (result exact or partial),
fewer skipped matches; username as a final deterministic fallback.

Request paths never aggregate: compute_ranking() runs only when a match is
scored (and as the phase-winner tiebreak); its result is persisted as
RankingEntry rows, which get_ranking() reads back.
"""

from types import SimpleNamespace

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum

from pool.models import Match, Prediction, RankingEntry


def compute_ranking():
    scored_match_count = Match.objects.filter(is_scored=True).count()

    stats_by_user = {
        row["user_id"]: row
        for row in (
            Prediction.objects.filter(match__is_scored=True)
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


def rebuild_ranking_snapshot():
    """Persist compute_ranking() as RankingEntry rows. Idempotent."""
    rows = compute_ranking()
    with transaction.atomic():
        RankingEntry.objects.all().delete()
        RankingEntry.objects.bulk_create(
            RankingEntry(
                user=row.user,
                position=row.position,
                total_points=row.total_points,
                exact_count=row.exact_count,
                winner_hit_count=row.winner_hit_count,
                skipped=row.skipped,
            )
            for row in rows
        )
    return rows


def get_ranking():
    """Read the pre-computed ranking. No aggregation — request-path safe.

    Users created after the last snapshot are appended at the bottom with
    zeros; before the first phase closes (empty snapshot) everyone is listed
    at zero.
    """
    entries = list(RankingEntry.objects.select_related("user"))
    known_ids = {e.user_id for e in entries}

    missing = User.objects.exclude(id__in=known_ids).order_by("username")
    next_position = len(entries) + 1
    for user in missing:
        entries.append(
            SimpleNamespace(
                user=user,
                position=next_position,
                total_points=0,
                exact_count=0,
                winner_hit_count=0,
                skipped=0,
            )
        )
        next_position += 1
    return entries
