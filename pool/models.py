from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone

KNOCKOUT_STAGES = [
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
    def flag_svg(self):
        # Self-hosted SVG path (flag-icons). Defensive: only a 2-letter ASCII
        # code maps to a flag; anything else (placeholder team, unmapped
        # country) falls back to a neutral placeholder rather than a 404.
        # SVGs are reliable across every OS/browser, unlike flag emoji (Windows
        # has no flag glyphs and renders the bare letters).
        code = (self.flag or "").lower()
        if len(code) == 2 and code.isascii() and code.isalpha():
            return f"pool/flags/{code}.svg"
        return "pool/flags/_placeholder.svg"

    def __str__(self):
        return f"{self.flag} {self.name}"


class Match(models.Model):
    STAGE_CHOICES = [
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
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES)
    # Phase string (FIFA matchday), e.g. "Group Stage - 1", "Round of 16".
    # Groups matches into phases (spec sections 3 and 7).
    phase = models.CharField(max_length=50, blank=True, default="")
    starts_at = models.DateTimeField()
    home_goals = models.IntegerField(null=True, blank=True)
    away_goals = models.IntegerField(null=True, blank=True)
    external_id = models.IntegerField(null=True, blank=True, unique=True)
    # Last status seen from the API (NS, 1H, HT, 2H, ET, FT, AET, PEN...).
    api_status = models.CharField(max_length=10, blank=True, default="NS")
    # Once True the match was scored and is never queried on the API again.
    is_scored = models.BooleanField(default=False)

    @property
    def is_knockout(self):
        return self.stage in KNOCKOUT_STAGES

    @property
    def prediction_deadline(self):
        return self.starts_at - timezone.timedelta(minutes=30)

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
            # Local import: scoring_service imports models.
            from pool.services.scoring_service import score_match

            score_match(self)


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
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "match")]

    def __str__(self):
        return f"{self.user} — {self.match} — {self.home_goals}×{self.away_goals}"


class RankingEntry(models.Model):
    """Pre-computed general ranking snapshot (spec sections 3 and 8).

    Rebuilt by rebuild_ranking_snapshot() whenever a phase closes, so the
    ranking page never aggregates predictions at request time.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    position = models.IntegerField()
    total_points = models.IntegerField(default=0)
    exact_count = models.IntegerField(default=0)
    winner_hit_count = models.IntegerField(default=0)
    skipped = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position"]

    def __str__(self):
        return f"#{self.position} {self.user} — {self.total_points} pts"


class PhaseWinner(models.Model):
    """Cached winner(s) of a closed phase (spec section 7).

    Computed once when the phase's last match is scored, so pages never
    re-aggregate. A phase may have multiple winners only when nobody scored
    (spec 7.4) — hence unique on (phase, user), not on phase alone.
    """

    phase = models.CharField(max_length=50)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    points = models.IntegerField()
    exact_count = models.IntegerField(default=0)
    partial_count = models.IntegerField(default=0)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("phase", "user")]

    def __str__(self):
        return f"{self.phase} — {self.user} — {self.points} pts"
