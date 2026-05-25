from django.contrib import admin
from .models import Team, Match, Prediction


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ["flag", "name"]

    search_fields = ["name"]


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = [
        "home_team",
        "away_team",
        "phase",
        "starts_at",
        "home_goals",
        "away_goals",
    ]

    list_filter = ["phase", "starts_at"]

    search_fields = ["home_team__name", "away_team__name"]

    readonly_fields = ["home_goals", "away_goals"]


@admin.register(Prediction)
class PredictionAdmin(admin.ModelAdmin):
    list_display = ["user", "match", "home_goals", "away_goals", "result", "points"]

    list_filter = ["result"]

    search_fields = ["user__username"]
