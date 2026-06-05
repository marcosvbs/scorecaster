"""Seed fictitious data for manual testing (NEVER run in production).

Creates demo users, teams and matches covering every UI state:
- a closed round (scored, with a round winner -> home card visible),
- the current round with locked / open / multi-day matches,
- future rounds (view-only tab), including a knockout match.

Usage:
    python manage.py seed_demo            # fails if matches already exist
    python manage.py seed_demo --reset    # wipes pool data first
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from pool.models import Match, Prediction, RoundWinner, Team

TEAMS = [
    ("Brasil", "BR"),
    ("Argentina", "AR"),
    ("França", "FR"),
    ("Alemanha", "DE"),
    ("Espanha", "ES"),
    ("Inglaterra", "GB"),
    ("Portugal", "PT"),
    ("México", "MX"),
]

DEMO_USERS = ["ana", "bruno", "carla"]
DEMO_PASSWORD = "demo123"


class Command(BaseCommand):
    help = "Seed fictitious matches/users for manual testing. Not for production."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete all pool data (matches, teams, predictions, winners) first.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["reset"]:
            Prediction.objects.all().delete()
            RoundWinner.objects.all().delete()
            Match.objects.all().delete()
            Team.objects.all().delete()
            self.stdout.write("Existing pool data wiped.")
        elif Match.objects.exists():
            raise CommandError(
                "Matches already exist. Re-run with --reset to wipe pool data first."
            )

        users = self._create_users()
        teams = self._create_teams()
        now = timezone.now()

        self._closed_round(teams, users, now)
        self._current_round(teams, now)
        self._future_rounds(teams, now)

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(
            f"Demo users: {', '.join(DEMO_USERS)} (password: {DEMO_PASSWORD})\n"
            "What to expect on the matches page:\n"
            "- Winner card: ana, 15 pts (disappears when the first current-round\n"
            "  match starts, in ~20 minutes)\n"
            "- Rodada atual: 1 locked (starts in 20 min), 2 open (today + tomorrow)\n"
            "- Próximos jogos: Group Stage - 3 and a Round of 16 knockout match\n"
            "Ranking: ana 15 > bruno 5 > carla 0. Historic: per-user results."
        )

    def _create_users(self):
        users = {}
        for username in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            users[username] = user
        return users

    def _create_teams(self):
        return {
            flag: Team.objects.create(name=name, flag=flag) for name, flag in TEAMS
        }

    def _make(self, home, away, starts_at, round_str, phase="group"):
        return Match.objects.create(
            home_team=home,
            away_team=away,
            phase=phase,
            round=round_str,
            starts_at=starts_at,
        )

    def _closed_round(self, teams, users, now):
        """Group Stage - 1: finished yesterday, scored, ana wins the round."""
        m1 = self._make(
            teams["BR"], teams["AR"], now - timedelta(days=1, hours=4), "Group Stage - 1"
        )
        m2 = self._make(
            teams["FR"], teams["DE"], now - timedelta(days=1), "Group Stage - 1"
        )

        # Predictions BEFORE results so the normal scoring pipeline runs.
        predictions = [
            (users["ana"], m1, 2, 0),    # exact -> 10
            (users["ana"], m2, 0, 0),    # correct draw -> 5
            (users["bruno"], m1, 1, 0),  # winner only -> 5
            (users["bruno"], m2, 2, 1),  # wrong -> 0
            (users["carla"], m1, 0, 1),  # wrong -> 0
            (users["carla"], m2, 1, 0),  # wrong -> 0
        ]
        for user, match, home_goals, away_goals in predictions:
            Prediction.objects.create(
                user=user, match=match, home_goals=home_goals, away_goals=away_goals
            )

        # Final scores: saving triggers scoring + round close + RoundWinner.
        m1.home_goals, m1.away_goals = 2, 0
        m1.save()
        m2.home_goals, m2.away_goals = 1, 1
        m2.save()

    def _current_round(self, teams, now):
        """Group Stage - 2: locked + open + multi-day (spans tomorrow)."""
        # Starts in 20 min: deadline (starts - 30 min) already passed -> locked,
        # but the match has not started, so the winner card is still visible.
        self._make(
            teams["ES"], teams["GB"], now + timedelta(minutes=20), "Group Stage - 2"
        )
        self._make(
            teams["PT"], teams["MX"], now + timedelta(hours=3), "Group Stage - 2"
        )
        self._make(
            teams["BR"], teams["FR"], now + timedelta(days=1), "Group Stage - 2"
        )

    def _future_rounds(self, teams, now):
        """View-only rounds in the 'Próximos jogos' tab."""
        self._make(
            teams["AR"], teams["MX"], now + timedelta(days=4), "Group Stage - 3"
        )
        self._make(
            teams["ES"], teams["DE"], now + timedelta(days=4, hours=3), "Group Stage - 3"
        )
        self._make(
            teams["BR"],
            teams["AR"],
            now + timedelta(days=8),
            "Round of 16",
            phase="round_of_16",
        )
