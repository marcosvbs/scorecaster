"""Admin maintenance routine: full reset to the pre-tournament state.

Wipes every user prediction and all data derived from predictions, and resets
every match back to "not played". Teams are untouched. All of it runs in one
transaction so a failure leaves the database exactly as it was (non-corrupting).
"""

from django.db import transaction

from pool.models import Match, Prediction, RankingEntry, RoundWinner


@transaction.atomic
def full_reset():
    """Delete all predictions + derived data and reset matches to pre-play.

    Returns a dict of counts (predictions, round_winners, ranking_entries,
    matches) for the confirmation message.
    """
    predictions = Prediction.objects.all().delete()[0]
    round_winners = RoundWinner.objects.all().delete()[0]
    ranking_entries = RankingEntry.objects.all().delete()[0]
    # Queryset update bypasses Match.save() — no scoring hook fires (it also
    # never would, since the goals are being set back to null).
    matches = Match.objects.update(
        home_goals=None, away_goals=None, is_scored=False, api_status="NS"
    )
    return {
        "predictions": predictions,
        "round_winners": round_winners,
        "ranking_entries": ranking_entries,
        "matches": matches,
    }
