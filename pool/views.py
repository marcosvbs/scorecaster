import json
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.views import LoginView
from django.db.models import Max
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse

from pool.models import Match, Prediction, PhaseWinner
from pool.services.ranking import get_ranking
from pool.services.phases import (
    current_phase_matches,
    future_phase_matches,
    is_match_in_current_phase,
)
from pool.services.throttle import (
    LOGIN_RATE_LIMIT,
    PREDICTION_RATE_LIMIT,
    client_ip,
    is_rate_limited,
)


class CustomLoginView(LoginView):
    template_name = "pool/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        max_requests, window = LOGIN_RATE_LIMIT
        if is_rate_limited(f"login:{client_ip(request)}", max_requests, window):
            # Plain form POST: re-render the page with a pt-BR message
            # instead of returning raw JSON.
            form = self.get_form()
            context = self.get_context_data(
                form=form,
                throttle_error=(
                    "Muitas tentativas de login. "
                    "Tente novamente em alguns minutos."
                ),
            )
            return self.render_to_response(context, status=429)
        return super().post(request, *args, **kwargs)


def _phase_winner_card(now):
    """Winner card data for the most recently closed phase (spec section 7).

    Shown from the moment the phase is scored until the first match of the
    next phase kicks off. Multiple winners (spec 7.4) are listed together.
    """
    closed_phase = (
        Match.objects.filter(is_scored=True)
        .exclude(phase__in=Match.objects.filter(is_scored=False).values("phase"))
        .values("phase")
        .annotate(last_start=Max("starts_at"))
        .order_by("-last_start")
        .first()
    )
    if not closed_phase:
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
        PhaseWinner.objects.filter(phase=closed_phase["phase"])
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
        phase=closed_phase["phase"],
        date=closed_phase["last_start"],
    )


@login_required
def matches(request):
    now = timezone.now()

    today_matches = (
        current_phase_matches()
        .order_by("starts_at")
        .select_related("home_team", "away_team")
    )

    upcoming_matches = (
        future_phase_matches()
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

        if match.is_scored or now >= match.prediction_deadline:
            match.status = "locked"
        elif user_pred:
            match.status = "predicted"
        else:
            match.status = "open"

    context = {
        "active_nav": "matches",
        "today_matches": today_matches,
        "upcoming_matches": upcoming_matches,
        "phase_winner": _phase_winner_card(now),
    }

    return render(request, "pool/matches.html", context)


@login_required
def ranking(request):
    context = {
        "active_nav": "ranking",
        # Pre-computed snapshot — no aggregation at request time.
        "ranking": get_ranking(),
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
    max_requests, window = PREDICTION_RATE_LIMIT
    if is_rate_limited(f"prediction:{request.user.id}", max_requests, window):
        return JsonResponse(
            {"ok": False, "error": "Too many requests. Try again soon."},
            status=429,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    match_id = data.get("match_id")
    home_goals = data.get("home_goals")
    away_goals = data.get("away_goals")

    if match_id is None or home_goals is None or away_goals is None:
        return JsonResponse({"ok": False, "error": "Missing fields."}, status=400)

    # JSON can carry strings/bools/floats; only true ints are valid (a bare
    # string here would make the range check below raise TypeError → 500).
    if not all(
        isinstance(g, int) and not isinstance(g, bool)
        for g in (home_goals, away_goals)
    ):
        return JsonResponse(
            {"ok": False, "error": "Goals must be integers."}, status=400
        )

    if not (0 <= home_goals <= 99) or not (0 <= away_goals <= 99):
        return JsonResponse(
            {"ok": False, "error": "Goals must be between 0 and 99."}, status=400
        )

    match = get_object_or_404(Match, id=match_id)

    # A scored match is locked even if its phase is still current and the
    # deadline has not passed (e.g. an admin set the result early).
    if match.is_scored:
        return JsonResponse(
            {"ok": False, "error": "Match is already scored."}, status=400
        )

    # Only the current phase accepts predictions (spec section 4).
    if not is_match_in_current_phase(match):
        return JsonResponse(
            {"ok": False, "error": "Match is not in the current phase."}, status=400
        )

    if timezone.now() >= match.prediction_deadline:
        return JsonResponse({"ok": False, "error": "Deadline has passed."}, status=400)

    Prediction.objects.update_or_create(
        user=request.user,
        match=match,
        defaults={"home_goals": home_goals, "away_goals": away_goals},
    )

    return JsonResponse({"ok": True})
