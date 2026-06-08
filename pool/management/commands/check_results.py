"""Time-driven result fetching and scoring (spec section 9).

Run by the container's internal scheduler every ~10 minutes. Ticks where no
match is past its expected end make ZERO API calls, so the schedule frequency
does not matter. A match that has not finished yet stays unscored and is
re-checked on the next tick.

Request economy: when anything is due, ONE `calendar/matches` request returns
the whole tournament, so a single call covers every due match (and resolves
knockout placeholder teams as the bracket fills in). Scored matches are never
queried again. Failures are logged and retried next tick; nothing is ever
marked scored on failure.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from pool.models import Match
from pool.services.fifa_api import FifaApiClient, FifaApiError, normalize_matches
from pool.services.fixtures import upsert_team
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
    help = "Fetch finished match results from api.fifa.com and score predictions."

    def handle(self, *args, **options):
        now = timezone.now()
        pending = Match.objects.filter(is_scored=False, external_id__isnull=False)
        due = [m for m in pending if now >= expected_check_time(m)]

        if not due:
            self.stdout.write("Nothing due. No API calls made.")
            return

        client = FifaApiClient()
        try:
            feed = {m["external_id"]: m for m in normalize_matches(client.get_all_matches())}
        except FifaApiError as exc:
            # Retry on the next tick; never mark anything scored here.
            logger.error("api.fifa.com fetch failed: %s", exc)
            self.stdout.write(self.style.ERROR("Fetch failed; will retry next tick."))
            return

        scored = 0
        for match in due:
            normalized = feed.get(match.external_id)
            if normalized is None:
                logger.warning(
                    "Match %s not present in feed; retrying next tick", match.external_id
                )
                continue
            scored += self._apply(match, normalized)

        self.stdout.write(
            self.style.SUCCESS(f"Checked {len(due)} match(es), scored {scored}.")
        )

    def _apply(self, match, normalized):
        # Resolve placeholder -> real teams as the knockout bracket fills in.
        match.home_team = upsert_team(normalized["home"])
        match.away_team = upsert_team(normalized["away"])
        match.api_status = normalized["status"]

        finished = (
            normalized["is_finished"]
            and normalized["home_goals"] is not None
            and normalized["away_goals"] is not None
        )
        if not finished:
            # Still in progress, or finished status without scores yet: persist
            # the latest teams/status and re-check next tick.
            match.save()
            logger.info(
                "Match %s not final yet (status %s), retrying next tick",
                match.external_id,
                normalized["status"],
            )
            return 0

        # Final score from FIFA HomeTeamScore/AwayTeamScore: includes extra
        # time, excludes the penalty shootout (spec section 6) — a 1x1 decided
        # on penalties scores as a 1x1 draw.
        match.home_goals = normalized["home_goals"]
        match.away_goals = normalized["away_goals"]
        match.save()  # triggers score_match when goals changed

        if not match.is_scored:
            # Goals already matched what was in the DB so save() didn't fire the
            # pipeline (e.g. admin had filled them in) — score explicitly.
            score_match(match)

        logger.info(
            "Match %s finished %s-%s, predictions scored",
            match.external_id,
            match.home_goals,
            match.away_goals,
        )
        return 1
