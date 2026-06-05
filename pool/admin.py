from django.contrib import admin
from .models import Team, Match, Prediction, RoundWinner


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

    list_filter = ["phase", "is_scored", "starts_at"]

    search_fields = ["home_team__name", "away_team__name"]


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ["user", "match", "home_goals", "away_goals", "result", "points"]

    list_filter = ["result"]

    search_fields = ["user__username"]


@admin.register(RoundWinner)
class RoundWinnerAdmin(admin.ModelAdmin):
    list_display = ["round", "user", "points", "exact_count", "partial_count"]

    list_filter = ["round"]
