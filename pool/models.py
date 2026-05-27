from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator

KNOCKOUT_PHASES = ["round_of_16", "quarter_final", "semi_final", "third_place", "final"]


class Team(models.Model):
    name = models.CharField(max_length=50)
    flag = models.CharField(max_length=4)

    @property
    def flag_emoji(self):
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.flag.upper())

    def __str__(self):
        return f"{self.flag} {self.name}"


class Match(models.Model):
    PHASE_CHOICES = [
        ("group", "Fase de Grupos"),
        ("round_of_16", "Oitavas de Final"),
        ("quarter_final", "Quartas de Final"),
        ("semi_final", "Semifinal"),
        ("third_place", "Disputa de Terceiro Lugar"),
        ("final", "Final"),
    ]

    home_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="home_matches"
    )
    away_team = models.ForeignKey(
        Team, on_delete=models.PROTECT, related_name="away_matches"
    )
    phase = models.CharField(max_length=20, choices=PHASE_CHOICES)
    starts_at = models.DateTimeField()
    home_goals = models.IntegerField(null=True, blank=True)
    away_goals = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} — {self.starts_at:%d/%m %Hh}"


class Prediction(models.Model):
    RESULT_CHOICES = [
        ("exact", "Exato"),
        ("partial", "Parcial"),
        ("wrong", "Errou"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    home_goals = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(99)]
    )
    away_goals = models.IntegerField(
        validators=[MinValueValidator(0), MaxValueValidator(99)]
    )
    points = models.IntegerField(null=True, blank=True)
    result = models.CharField(
        max_length=10, choices=RESULT_CHOICES, null=True, blank=True
    )

    class Meta:
        unique_together = [("user", "match")]

    def __str__(self):
        return f"{self.user} — {self.match} — {self.home_goals}×{self.away_goals}"
