import json
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.contrib.auth.views import LoginView
from django.shortcuts import render, get_object_or_404
from pool.models import Match, Prediction
from django.utils import timezone
from django.http import JsonResponse


class CustomLoginView(LoginView):
    template_name = "pool/login.html"
    redirect_authenticated_user = True


@login_required
def matches(request):
    local_now = timezone.localtime(timezone.now())
    today = local_now.date()

    today_matches = (
        Match.objects.filter(starts_at__date=today)
        .order_by("starts_at")
        .select_related("home_team", "away_team")
    )

    upcoming_matches = (
        Match.objects.filter(starts_at__date__gt=today)
        .order_by("starts_at")
        .select_related("home_team", "away_team")
    )

    user_predictions = Prediction.objects.filter(
        user=request.user, match__in=today_matches
    )

    predictions_by_match = {p.match_id: p for p in user_predictions}

    KNOCKOUT_PHASES = [
        "round_of_16",
        "quarter_final",
        "semi_final",
        "third_place",
        "final",
    ]

    for match in today_matches:
        deadline = timezone.localtime(match.starts_at) - timezone.timedelta(minutes=30)
        match.prediction_deadline = deadline
        match.is_knockout = match.phase in KNOCKOUT_PHASES
        user_pred = predictions_by_match.get(match.id)
        match.user_prediction = user_pred

        if local_now >= deadline:
            match.status = "locked"
        elif user_pred:
            match.status = "predicted"
        else:
            match.status = "open"

    context = {
        "active_nav": "matches",
        "today_matches": today_matches,
        "upcoming_matches": upcoming_matches,
        "round_winner": None,  # fase 6
    }

    return render(request, "pool/matches.html", context)


@login_required
def ranking(request):
    return render(request, "pool/ranking.html", {"active_nav": "ranking"})


@login_required
def historic(request):
    return render(request, "pool/historic.html", {"active_nav": "historic"})


@login_required
def save_prediction(request):
    pass


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
    local_now = timezone.localtime(timezone.now())
    prediction_deadline = match.starts_at - timezone.timedelta(minutes=30)

    if local_now >= prediction_deadline:
        return JsonResponse({"ok": False, "error": "Deadline has passed."}, status=400)

    Prediction.objects.update_or_create(
        user=request.user,
        match=match,
        defaults={"home_goals": home_goals, "away_goals": away_goals},
    )

    return JsonResponse({"ok": True})
