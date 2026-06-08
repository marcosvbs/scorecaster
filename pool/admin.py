from django.contrib import admin
from django.http import HttpResponse

from .models import Team, Match, Prediction, RoundWinner
from .services.throttle import LOGIN_RATE_LIMIT, client_ip, is_rate_limited

# The admin login form takes password guesses like any other; throttle it
# with the SAME key as the site login so an IP gets one shared budget.
_original_admin_login = admin.site.login


def _throttled_admin_login(request, extra_context=None):
    if request.method == "POST":
        max_requests, window = LOGIN_RATE_LIMIT
        if is_rate_limited(f"login:{client_ip(request)}", max_requests, window):
            return HttpResponse(
                "Muitas tentativas de login. Tente novamente em alguns minutos.",
                status=429,
            )
    return _original_admin_login(request, extra_context)


admin.site.login = _throttled_admin_login


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["flag", "name", "external_id"]

    search_fields = ["name"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    # Saving a result here triggers the same scoring + round-close pipeline as
    # the automatic flow (Match.save), so manual updates stay consistent.
    list_display = [
        "home_team",
        "away_team",
        "phase",
        "round",
        "starts_at",
        "home_goals",
        "away_goals",
        "api_status",
        "is_scored",
        "external_id",
    ]

    # Edit results straight from the changelist; each row save runs Match.save()
    # → the full scoring + round-close + ranking cascade.
    list_editable = ["home_goals", "away_goals"]

    list_filter = ["phase", "is_scored", "starts_at"]

    ordering = ["starts_at"]

    search_fields = ["home_team__name", "away_team__name"]


class _ReadOnlyAdmin(admin.ModelAdmin):
    """Visible for inspection, but never editable: these rows are recomputed by
    the scoring pipeline, so manual edits would not cascade (and would mislead)."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Prediction)
class PredictionAdmin(_ReadOnlyAdmin):
    list_display = ["user", "match", "home_goals", "away_goals", "result", "points"]

    list_filter = ["result"]

    search_fields = ["user__username"]


@admin.register(RoundWinner)
class RoundWinnerAdmin(_ReadOnlyAdmin):
    list_display = ["round", "user", "points", "exact_count", "partial_count"]

    list_filter = ["round"]
