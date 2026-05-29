from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from pool.utils.scoring import calculate_points

KNOCKOUT_PHASES = [
    "round_of_32",
    "round_of_16",
    "quarter_final",
    "semi_final",
    "third_place",
    "final",
]


class Team(models.Model):
    name = models.CharField(max_length=50)
    flag = models.CharField(max_length=4)
    external_id = models.IntegerField(null=True, blank=True, unique=True)

    @property
    def flag_emoji(self):
        return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in self.flag.upper())

    def __str__(self):
        return f"{self.flag} {self.name}"


class Match(models.Model):
    PHASE_CHOICES = [
        ("group", "Fase de Grupos"),
        ("round_of_32", "32-avos de Final"),
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
    external_id = models.IntegerField(null=True, blank=True, unique=True)

    @property
    def is_knockout(self):
        return self.phase in KNOCKOUT_PHASES

    def __str__(self):
        return f"{self.home_team} vs {self.away_team} — {self.starts_at:%d/%m %Hh}"

    def save(self, *args, **kwargs):
        if self.pk:
            previous = Match.objects.get(pk=self.pk)
            goals_changed = (
                previous.home_goals != self.home_goals
                or previous.away_goals != self.away_goals
            )
            should_score = (
                goals_changed
                and self.home_goals is not None
                and self.away_goals is not None
            )
        else:
            should_score = False

        super().save(*args, **kwargs)

        if should_score:
            predictions = list(Prediction.objects.filter(match=self))

            for p in predictions:
                points, result = calculate_points(
                    p.home_goals, p.away_goals, self.home_goals, self.away_goals
                )
                p.points = points
                p.result = result

            Prediction.objects.bulk_update(predictions, ["points", "result"])


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
