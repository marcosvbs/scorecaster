"""Time-driven result fetching and scoring (spec section 9).

Run by the container's internal scheduler every ~10 minutes. Ticks where no
match is past its expected end make ZERO API calls, so the schedule frequency
does not matter. A match that has not finished yet stays unscored and is
re-checked on the next tick.

Request economy: a fetch happens only when (a) a match is past its expected end
(due for scoring) or (b) the current phase still has placeholder teams that need
resolving — otherwise zero API calls. When anything triggers a fetch, ONE
`calendar/matches` request returns the whole tournament, so the single call both
scores every due match AND resolves placeholder teams for every unscored match
the bracket has filled in (team resolution is decoupled from scoring, so a
knockout phase shows its real teams during the prediction window, not ~3h after
each match kicks off). Scored matches are never queried again. Failures are
logged and retried next tick; nothing is ever marked scored on failure.
"""

import logging

from django.core.management.base import BaseCommand
from django.utils import timezone

from pool.models import Match
from pool.services.fifa_api import FifaApiClient, FifaApiError, normalize_matches
from pool.services.fixtures import upsert_team
from pool.services.phases import current_phase_matches
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
        pending = list(
            Match.objects.filter(
                is_scored=False, external_id__isnull=False
            ).select_related("home_team", "away_team")
        )
        due = [m for m in pending if now >= expected_check_time(m)]

        # Current phase = what users predict now. If it still carries placeholder
        # teams (knockout slots not yet resolved to the qualified team), fetch to
        # fill them in even when nothing is due for scoring. Bounded to the
        # current phase, so far-future placeholders never trigger a call.
        unresolved = [
            m
            for m in current_phase_matches().select_related("home_team", "away_team")
            if not m.is_scored
            and m.external_id is not None
            and m.is_knockout  # only knockout slots are ever placeholders
            and (m.home_team.external_id is None or m.away_team.external_id is None)
        ]

        if not due and not unresolved:
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

        # Resolve placeholder -> real teams for every unscored match the feed
        # knows about (free: same single request). Due matches are skipped here
        # and get their teams set in _apply alongside scoring.
        due_ids = {m.external_id for m in due}
        resolved = 0
        for match in pending:
            if match.external_id in due_ids:
                continue
            normalized = feed.get(match.external_id)
            if normalized is not None and self._resolve_teams(match, normalized):
                resolved += 1

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
            self.style.SUCCESS(
                f"Checked {len(due)} match(es), scored {scored}, "
                f"resolved {resolved} placeholder match(es)."
            )
        )

    def _resolve_teams(self, match, normalized):
        """Update a match's teams/status from the feed; save only when changed.

        Decoupled from scoring so knockout placeholder slots (e.g. "1F"/"3CDFGH")
        become real teams as soon as the bracket fills, not 3h after kickoff.
        Returns True when a write happened.
        """
        new_home = upsert_team(normalized["home"])
        new_away = upsert_team(normalized["away"])
        if (
            match.home_team_id == new_home.id
            and match.away_team_id == new_away.id
            and match.api_status == normalized["status"]
        ):
            return False
        match.home_team = new_home
        match.away_team = new_away
        match.api_status = normalized["status"]
        match.save()
        return True

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
