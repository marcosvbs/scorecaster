import json
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.views.decorators.http import require_GET, require_POST
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator
from django.contrib.auth.views import LoginView
from django.db.models import Max
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.http import JsonResponse

from pool.models import Match, Prediction, PhaseWinner
from pool.services.ranking import get_phase_ranking, get_ranking
from pool.services.phases import (
    current_phase_matches,
    future_phase_matches,
    is_match_in_current_phase,
)
from pool.services.throttle import (
    LOGIN_RATE_LIMIT,
    OTHERS_RATE_LIMIT,
    PREDICTION_RATE_LIMIT,
    client_ip,
    is_rate_limited,
)


@method_decorator(never_cache, name="dispatch")
class CustomLoginView(LoginView):
    # never_cache: the login form must never be served from the browser/bfcache.
    # Django rotates the CSRF token on login, so a stale cached form would carry
    # an outdated token and POST back a "CSRF verification failed" 403.
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


@never_cache
def csrf_failure(request, reason=""):
    """Friendly CSRF-failure page (Django CSRF_FAILURE_VIEW).

    Instead of the raw Django 403, re-render the login form with a fresh
    {% csrf_token %} (new cookie + token) and a pt-BR retry message, so the
    user can simply log in again. Wired via CSRF_FAILURE_VIEW in settings.
    """
    context = {
        "form": AuthenticationForm(),
        "csrf_error": "Sua sessão expirou. Atualize a página e tente novamente.",
    }
    return render(request, "pool/login.html", context, status=403)


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


def _demo_context(request):
    """Demo flags for templates.

    Both attrs are set ONLY by the offline ``render_demo`` command on its
    in-process request. Real production requests never set them, so this
    returns the off/empty defaults and the live pages are unaffected.
    """
    return {
        "is_demo": getattr(request, "is_demo", False),
        "demo_others_json": getattr(request, "demo_others_json", "{}"),
    }


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

        # Lifecycle order, most-terminal first: a scored match is "finished";
        # past kickoff but unscored is "live"; past the 30-min deadline but
        # before kickoff is "locked"; otherwise it still accepts predictions.
        if match.is_scored:
            match.status = "finished"
        elif now >= match.starts_at:
            match.status = "live"
        elif now >= match.prediction_deadline:
            match.status = "locked"
        elif user_pred:
            match.status = "predicted"
        else:
            match.status = "open"

    context = {
        "active_nav": "matches",
        "today_matches": today_matches,
        "upcoming_matches": upcoming_matches,
        "has_finished_today": any(m.status == "finished" for m in today_matches),
        "phase_winner": _phase_winner_card(now),
        **_demo_context(request),
    }

    return render(request, "pool/matches.html", context)


@login_required
def ranking(request):
    # Pre-computed snapshot — no aggregation at request time. The per-phase
    # leaderboard is the same rows re-sorted by the focus-phase metrics.
    phase_ranking = get_phase_ranking()
    current_phase = phase_ranking[0].phase if phase_ranking else ""
    context = {
        "active_nav": "ranking",
        "ranking": get_ranking(),
        "phase_ranking": phase_ranking,
        "current_phase": current_phase,
        "total_matches": Match.objects.filter(is_scored=True).count(),
        **_demo_context(request),
    }
    return render(request, "pool/ranking.html", context)


@login_required
def historic(request):
    user_predictions = Prediction.objects.filter(user=request.user)
    stats = {
        "total_points": sum(p.points or 0 for p in user_predictions),
        "exact_count": sum(1 for p in user_predictions if p.result == "exact"),
        "partial_count": sum(1 for p in user_predictions if p.result == "partial"),
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
        **_demo_context(request),
    }
    return render(request, "pool/historic.html", context)


@login_required
@require_GET
def match_predictions(request, match_id):
    """Other users' predictions for a match (the "Outros palpites" modal).

    Read-only, DB-only. Predictions are revealed ONLY once the match is live
    (kicked off) or finished (scored) — never before kickoff, so it can't leak
    guesses while betting is still open. This guard is the privacy invariant and
    lives here (not the template): the client cannot request it early.
    """
    max_requests, window = OTHERS_RATE_LIMIT
    if is_rate_limited(f"others:{request.user.id}", max_requests, window):
        return JsonResponse(
            {"ok": False, "error": "Too many requests. Try again soon."},
            status=429,
        )

    match = get_object_or_404(
        Match.objects.select_related("home_team", "away_team"), id=match_id
    )

    # Reveal guard — palpites become visible once they can no longer change:
    # at the 30-min prediction deadline (covers locked + live) or once scored.
    # A still-open match (before its deadline) stays hidden so nobody can copy.
    if not (match.is_scored or timezone.now() >= match.prediction_deadline):
        return JsonResponse(
            {"ok": False, "error": "Predictions not yet visible."}, status=403
        )

    def serialize(prediction):
        return {
            "username": prediction.user.username,
            "home_goals": prediction.home_goals,
            "away_goals": prediction.away_goals,
            # result/points only meaningful once the match is scored.
            "result": prediction.result if match.is_scored else None,
            "points": prediction.points if match.is_scored else None,
        }

    others = (
        Prediction.objects.filter(match=match)
        .exclude(user=request.user)
        .select_related("user")
    )
    # Finished: rank by points so the best guesses surface first.
    others = others.order_by(
        *(("-points", "user__username") if match.is_scored else ("user__username",))
    )

    viewer_pred = Prediction.objects.filter(match=match, user=request.user).first()
    if viewer_pred is not None:
        viewer = serialize(viewer_pred)
        viewer["predicted"] = True
    else:
        # The viewer skipped this match — still surface a self row.
        viewer = {
            "username": request.user.username,
            "predicted": False,
            "home_goals": None,
            "away_goals": None,
            "result": None,
            "points": None,
        }

    return JsonResponse(
        {
            "ok": True,
            "is_finished": match.is_scored,
            "viewer": viewer,
            "predictions": [serialize(p) for p in others],
        }
    )


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
