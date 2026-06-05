"""One-off pre-launch import of teams and fixtures (spec section 9).

Idempotent: teams and matches are upserted by external_id, so re-running
before launch is safe. On API failure nothing partial is written.

Usage: python manage.py seed_world_cup [--league 1] [--season 2026] [--dry-run]
"""

import logging
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from pool.models import Match, Team
from pool.services.api_football import ApiFootballClient, ApiFootballError
from pool.services.rounds import phase_from_round

logger = logging.getLogger(__name__)

# FIFA 3-letter code -> ISO-2 code used by Team.flag_emoji.
FIFA_TO_ISO2 = {
    "ALG": "DZ", "ARG": "AR", "AUS": "AU", "AUT": "AT", "BEL": "BE",
    "BOL": "BO", "BRA": "BR", "CAN": "CA", "CHI": "CL", "COL": "CO",
    "CRC": "CR", "CRO": "HR", "CUW": "CW", "CIV": "CI", "DEN": "DK",
    "ECU": "EC", "EGY": "EG", "ENG": "GB", "ESP": "ES", "FRA": "FR",
    "GER": "DE", "GHA": "GH", "GRE": "GR", "HAI": "HT", "HON": "HN",
    "IRN": "IR", "IRQ": "IQ", "ITA": "IT", "JAM": "JM", "JPN": "JP",
    "JOR": "JO", "KOR": "KR", "KSA": "SA", "MAR": "MA", "MEX": "MX",
    "NED": "NL", "NZL": "NZ", "NGA": "NG", "NOR": "NO", "PAN": "PA",
    "PAR": "PY", "PER": "PE", "POL": "PL", "POR": "PT", "QAT": "QA",
    "RSA": "ZA", "SCO": "GB", "SEN": "SN", "SRB": "RS", "SUI": "CH",
    "SWE": "SE", "TUN": "TN", "TUR": "TR", "UKR": "UA", "URU": "UY",
    "USA": "US", "UZB": "UZ", "VEN": "VE", "WAL": "GB", "CMR": "CM",
    "CPV": "CV",
}


def iso2_from_team(team_data):
    code = (team_data.get("code") or "").upper()
    if code in FIFA_TO_ISO2:
        return FIFA_TO_ISO2[code]
    if len(code) >= 2:
        logger.warning("No ISO-2 mapping for team code %r, using prefix", code)
        return code[:2]
    return ""


class Command(BaseCommand):
    help = "Import World Cup teams and fixtures from API-Football (run once pre-launch)."

    def add_arguments(self, parser):
        parser.add_argument("--league", type=int, default=None)
        parser.add_argument("--season", type=int, default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        client = ApiFootballClient()
        try:
            teams = client.get_teams(league=options["league"], season=options["season"])
            fixtures = client.get_fixtures(
                league=options["league"], season=options["season"]
            )
        except ApiFootballError as exc:
            raise CommandError(f"API-Football request failed: {exc}") from exc

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {len(teams)} teams, {len(fixtures)} fixtures fetched."
            )
            return

        with transaction.atomic():
            team_count = self._upsert_teams(teams)
            match_count = self._upsert_fixtures(fixtures)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {team_count} teams and {match_count} matches."
            )
        )

    def _upsert_teams(self, teams):
        count = 0
        for entry in teams:
            data = entry["team"]
            Team.objects.update_or_create(
                external_id=data["id"],
                defaults={"name": data["name"], "flag": iso2_from_team(data)},
            )
            count += 1
        return count

    def _upsert_fixtures(self, fixtures):
        count = 0
        for entry in fixtures:
            fixture = entry["fixture"]
            round_str = entry["league"]["round"]
            home, away = entry["teams"]["home"], entry["teams"]["away"]

            home_team, _ = Team.objects.get_or_create(
                external_id=home["id"],
                defaults={"name": home["name"], "flag": iso2_from_team(home)},
            )
            away_team, _ = Team.objects.get_or_create(
                external_id=away["id"],
                defaults={"name": away["name"], "flag": iso2_from_team(away)},
            )

            Match.objects.update_or_create(
                external_id=fixture["id"],
                defaults={
                    "home_team": home_team,
                    "away_team": away_team,
                    "starts_at": datetime.fromisoformat(fixture["date"]),
                    "round": round_str,
                    "phase": phase_from_round(round_str),
                    "api_status": fixture["status"]["short"],
                },
            )
            count += 1
        return count
