import json
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.views import LoginView
from django.db.models import Max
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse

from pool.models import Match, Prediction, RoundWinner
from pool.services.ranking import compute_ranking
from pool.services.rounds import (
    current_round_matches,
    future_round_matches,
    is_match_in_current_round,
)


class CustomLoginView(LoginView):
    template_name = "pool/login.html"
    redirect_authenticated_user = True


def _round_winner_card(now):
    """Winner card data for the most recently closed round (spec section 7).

    Shown from the moment the round is scored until the first match of the
    next round kicks off. Multiple winners (spec 7.4) are listed together.
    """
    closed_round = (
        Match.objects.filter(is_scored=True)
        .exclude(round__in=Match.objects.filter(is_scored=False).values("round"))
        .values("round")
        .annotate(last_start=Max("starts_at"))
        .order_by("-last_start")
        .first()
    )
    if not closed_round:
        return None

    next_first_start = (
        Match.objects.filter(is_scored=False)
        .order_by("starts_at")
        .values_list("starts_at", flat=True)
        .first()
    )
    if next_first_start is not None and next_first_start <= now:
        return None

    winners = list(
        RoundWinner.objects.filter(round=closed_round["round"])
        .select_related("user")
        .order_by("user__username")
    )
    if not winners:
        return None

    first = winners[0]
    return SimpleNamespace(
        user=SimpleNamespace(
            username=", ".join(w.user.username for w in winners)
        ),
        points=first.points,
        exact_count=first.exact_count,
        partial_count=first.partial_count,
        date=closed_round["last_start"],
    )


@login_required
def matches(request):
    now = timezone.now()

    today_matches = (
        current_round_matches()
        .order_by("starts_at")
        .select_related("home_team", "away_team")
    )

    upcoming_matches = (
        future_round_matches()
        .order_by("starts_at")
        .select_related("home_team", "away_team")
    )

    user_predictions = Prediction.objects.filter(
        user=request.user, match__in=today_matches
    )

    predictions_by_match = {p.match_id: p for p in user_predictions}

    for match in today_matches:
        user_pred = predictions_by_match.get(match.id)
        match.user_prediction = user_pred

        if now >= match.prediction_deadline:
            match.status = "locked"
        elif user_pred:
            match.status = "predicted"
        else:
            match.status = "open"

    context = {
        "active_nav": "matches",
        "today_matches": today_matches,
        "upcoming_matches": upcoming_matches,
        "round_winner": _round_winner_card(now),
    }

    return render(request, "pool/matches.html", context)


@login_required
def ranking(request):
    context = {
        "active_nav": "ranking",
        "ranking": compute_ranking(),
        "total_matches": Match.objects.filter(is_scored=True).count(),
    }
    return render(request, "pool/ranking.html", context)


@login_required
def historic(request):
    user_predictions = Prediction.objects.filter(user=request.user)
    stats = {
        "total_points": sum(p.points or 0 for p in user_predictions),
        "exact_count": sum(1 for p in user_predictions if p.result == "exact"),
        "total_predictions": len(user_predictions),
    }

    predictions_by_match = {p.match_id: p for p in user_predictions}
    scored_matches = (
        Match.objects.filter(is_scored=True)
        .order_by("-starts_at")
        .select_related("home_team", "away_team")
    )
    entries = []
    for match in scored_matches:
        prediction = predictions_by_match.get(match.id)
        if prediction:
            entries.append(prediction)
        else:
            # No prediction: shows as 'none' in history, no penalty (spec 5).
            entries.append(SimpleNamespace(match=match, result="none"))

    context = {
        "active_nav": "historic",
        "stats": stats,
        "predictions": entries,
    }
    return render(request, "pool/historic.html", context)


@login_required
@require_POST
def save_prediction(request):
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    match_id = data.get("match_id")
    home_goals = data.get("home_goals")
    away_goals = data.get("away_goals")

    if match_id is None or home_goals is None or away_goals is None:
        return JsonResponse({"ok": False, "error": "Missing fields."}, status=400)

    if not (0 <= home_goals <= 99) or not (0 <= away_goals <= 99):
        return JsonResponse(
            {"ok": False, "error": "Goals must be between 0 and 99."}, status=400
        )

    match = get_object_or_404(Match, id=match_id)

    # Only the current round accepts predictions (spec section 4).
    if not is_match_in_current_round(match):
        return JsonResponse(
            {"ok": False, "error": "Match is not in the current round."}, status=400
        )

    if timezone.now() >= match.prediction_deadline:
        return JsonResponse({"ok": False, "error": "Deadline has passed."}, status=400)

    Prediction.objects.update_or_create(
        user=request.user,
        match=match,
        defaults={"home_goals": home_goals, "away_goals": away_goals},
    )

    return JsonResponse({"ok": True})
