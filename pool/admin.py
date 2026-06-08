from django.contrib import admin, messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse

from .models import Team, Match, Prediction, RankingEntry, RoundWinner
from .services.reset import full_reset
from .services.throttle import LOGIN_RATE_LIMIT, client_ip, is_rate_limited

# Word the admin must type to confirm the destructive full reset.
RESET_CONFIRM_WORD = "ZERAR"

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

    # Adds the "Zerar palpites e resultados" button to the changelist toolbar.
    change_list_template = "admin/pool/prediction/change_list.html"

    def get_urls(self):
        # admin_site.admin_view enforces staff login; the view itself adds a
        # superuser check on top, since the reset is irreversible.
        custom = [
            path(
                "full-reset/",
                self.admin_site.admin_view(self.full_reset_view),
                name="pool_prediction_full_reset",
            ),
        ]
        return custom + super().get_urls()

    def full_reset_view(self, request):
        if not request.user.is_superuser:
            self.message_user(
                request,
                "Apenas superusuários podem zerar os dados.",
                level=messages.ERROR,
            )
            return redirect("admin:pool_prediction_changelist")

        if request.method == "POST":
            if request.POST.get("confirm") != RESET_CONFIRM_WORD:
                self.message_user(
                    request,
                    "Confirmação incorreta. Nenhum dado foi alterado.",
                    level=messages.WARNING,
                )
                return redirect("admin:pool_prediction_full_reset")

            counts = full_reset()
            self.message_user(
                request,
                "Dados zerados: {predictions} palpites, {round_winners} "
                "vencedores de rodada, {ranking_entries} posições do ranking "
                "removidos; {matches} jogos reiniciados.".format(**counts),
                level=messages.SUCCESS,
            )
            return redirect("admin:pool_prediction_changelist")

        context = {
            **self.admin_site.each_context(request),
            "title": "Zerar palpites e resultados",
            "confirm_word": RESET_CONFIRM_WORD,
            "counts": {
                "predictions": Prediction.objects.count(),
                "round_winners": RoundWinner.objects.count(),
                "ranking_entries": RankingEntry.objects.count(),
                "scored_matches": Match.objects.filter(is_scored=True).count(),
            },
            "changelist_url": reverse("admin:pool_prediction_changelist"),
        }
        return render(request, "admin/pool/prediction/full_reset_confirm.html", context)


@admin.register(RoundWinner)
class RoundWinnerAdmin(_ReadOnlyAdmin):
    list_display = ["round", "user", "points", "exact_count", "partial_count"]

    list_filter = ["round"]
