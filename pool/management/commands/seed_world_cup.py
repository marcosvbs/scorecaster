"""One-off pre-launch import of teams and fixtures from api.fifa.com.

Idempotent: teams and matches are upserted by external_id (real teams) or by
name (knockout placeholder slots), so re-running before launch is safe. One
`calendar/matches` request returns the full tournament — every team, all group
matches, and the knockout bracket as placeholder slots ("2A", "W73", ...) that
the `check_results` updater later resolves to real teams.

On API failure nothing partial is written (single transaction).

Usage: python manage.py seed_world_cup [--competition 17] [--season 285023] [--dry-run]
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pool.models import Team
from pool.services.fifa_api import FifaApiClient, FifaApiError, normalize_matches
from pool.services.fixtures import seed_match

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Import World Cup teams and fixtures from api.fifa.com (run once pre-launch)."

    def add_arguments(self, parser):
        parser.add_argument("--competition", type=str, default=None)
        parser.add_argument("--season", type=str, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        client = FifaApiClient(
            competition_id=options["competition"], season_id=options["season"]
        )
        try:
            matches = normalize_matches(client.get_all_matches())
        except FifaApiError as exc:
            raise CommandError(f"api.fifa.com request failed: {exc}") from exc

        if not matches:
            raise CommandError("No matches returned from api.fifa.com.")

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {len(matches)} matches fetched.")
            return

        with transaction.atomic():
            for match in matches:
                seed_match(match)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {Team.objects.count()} teams and {len(matches)} matches."
            )
        )
