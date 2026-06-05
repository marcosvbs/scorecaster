"""Time-driven result fetching and scoring (spec section 9).

Run by an external scheduler (Railway cron) every ~10 minutes. Ticks where
no match is past its expected end make ZERO API calls, so the schedule
frequency does not burn the daily quota. A match that has not finished yet
simply stays unscored and is re-checked on the next tick — that IS the
low-frequency extraordinary routine from the spec.

Request economy: due matches are grouped by date, one request per date.
Scored matches are never queried again. Failures are logged and retried on
the next tick; nothing is ever marked scored on failure.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from pool.models import FINISHED_STATUSES, Match
from pool.services.api_football import ApiFootballClient, ApiFootballError
from pool.services.scoring_service import score_match

logger = logging.getLogger(__name__)

# Expected real-world duration before checking the result (spec section 9):
# group games ~1h50 of clock; knockout waits for extra time + penalties.
GROUP_CHECK_OFFSET = timezone.timedelta(hours=1, minutes=50)
KNOCKOUT_CHECK_OFFSET = timezone.timedelta(hours=2, minutes=45)


def expected_check_time(match):
    offset = KNOCKOUT_CHECK_OFFSET if match.is_knockout else GROUP_CHECK_OFFSET
    return match.starts_at + offset


class Command(BaseCommand):
    help = "Fetch finished match results from API-Football and score predictions."

    def handle(self, *args, **options):
        now = timezone.now()
        pending = Match.objects.filter(is_scored=False, external_id__isnull=False)
        due = [m for m in pending if now >= expected_check_time(m)]

        if not due:
            self.stdout.write("Nothing due. No API calls made.")
            return

        by_date = {}
        for match in due:
            by_date.setdefault(match.starts_at.date().isoformat(), []).append(match)

        client = ApiFootballClient()
        scored = 0
        for date_str, matches in sorted(by_date.items()):
            try:
                fixtures = client.get_fixtures_by_date(date_str)
            except ApiFootballError as exc:
                # Retry on the next tick; never mark anything scored here.
                logger.error("Fetch for %s failed: %s", date_str, exc)
                continue

            fixtures_by_id = {f["fixture"]["id"]: f for f in fixtures}
            for match in matches:
                fixture = fixtures_by_id.get(match.external_id)
                if fixture is None:
                    logger.warning(
                        "Fixture %s not in API response for %s",
                        match.external_id,
                        date_str,
                    )
                    continue
                scored += self._apply(match, fixture)

        self.stdout.write(
            self.style.SUCCESS(f"Checked {len(due)} match(es), scored {scored}.")
        )

    def _apply(self, match, fixture):
        status = fixture["fixture"]["status"]["short"]
        if status not in FINISHED_STATUSES:
            match.api_status = status
            match.save(update_fields=["api_status"])
            logger.info(
                "Match %s still in progress (%s), retrying next tick",
                match.external_id,
                status,
            )
            return 0

        # Final score: API 'goals' includes extra time but never penalties
        # (spec section 6) — a 1x1 decided on penalties scores as a 1x1 draw.
        match.home_goals = fixture["goals"]["home"]
        match.away_goals = fixture["goals"]["away"]
        match.api_status = status
        match.save()  # triggers score_match when goals changed

        if not match.is_scored:
            # Goals already matched what was in the DB (e.g. admin had filled
            # them in) so save() didn't fire the pipeline — score explicitly.
            score_match(match)

        logger.info(
            "Match %s finished %s-%s (%s), predictions scored",
            match.external_id,
            match.home_goals,
            match.away_goals,
            status,
        )
        return 1
