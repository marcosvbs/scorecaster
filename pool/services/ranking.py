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
from pool.services.phases import focus_phase


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

    # Focus-phase breakdown: the live per-phase race shown on the Ranking tab.
    # Aggregated here (scoring time) so the request path stays read-only.
    fp = focus_phase()
    phase_stats_by_user = {}
    if fp:
        phase_stats_by_user = {
            row["user_id"]: row
            for row in (
                Prediction.objects.filter(match__is_scored=True, match__phase=fp)
                .values("user_id")
                .annotate(
                    phase_points=Sum("points"),
                    phase_exact_count=Count("id", filter=Q(result="exact")),
                    phase_winner_hit_count=Count(
                        "id", filter=Q(result__in=["exact", "partial"])
                    ),
                )
            )
        }

    rows = []
    for user in User.objects.all():
        stats = stats_by_user.get(user.id, {})
        phase_stats = phase_stats_by_user.get(user.id, {})
        prediction_count = stats.get("prediction_count", 0)
        rows.append(
            SimpleNamespace(
                user=user,
                total_points=stats.get("total_points") or 0,
                exact_count=stats.get("exact_count", 0),
                winner_hit_count=stats.get("winner_hit_count", 0),
                skipped=scored_match_count - prediction_count,
                phase=fp or "",
                phase_points=phase_stats.get("phase_points") or 0,
                phase_exact_count=phase_stats.get("phase_exact_count", 0),
                phase_winner_hit_count=phase_stats.get(
                    "phase_winner_hit_count", 0
                ),
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
                phase=row.phase,
                phase_points=row.phase_points,
                phase_exact_count=row.phase_exact_count,
                phase_winner_hit_count=row.phase_winner_hit_count,
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
                phase="",
                phase_points=0,
                phase_exact_count=0,
                phase_winner_hit_count=0,
            )
        )
        next_position += 1
    return entries


def get_phase_ranking():
    """The focus-phase leaderboard: same snapshot rows, re-sorted by phase.

    Pure in-memory sort of the pre-computed RankingEntry rows — no aggregation,
    so it is request-path safe. Tiebreak mirrors the general ranking on the
    phase metrics: phase points, exact hits, winner hits, then username.
    Rank 1 is flagged `is_phase_leader` (the would-be Vencedor da fase) only
    when it has scored any points.
    """
    entries = get_ranking()
    ordered = sorted(
        entries,
        key=lambda e: (
            -e.phase_points,
            -e.phase_exact_count,
            -e.phase_winner_hit_count,
            e.user.username.lower(),
        ),
    )
    ranked = []
    for position, entry in enumerate(ordered, start=1):
        ranked.append(
            SimpleNamespace(
                user=entry.user,
                position=position,
                phase=entry.phase,
                phase_points=entry.phase_points,
                phase_exact_count=entry.phase_exact_count,
                phase_winner_hit_count=entry.phase_winner_hit_count,
                total_points=entry.total_points,
                is_phase_leader=position == 1 and entry.phase_points > 0,
            )
        )
    return ranked
