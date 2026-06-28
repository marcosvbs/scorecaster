"""Time-driven result fetching and scoring (spec section 9).

Run by the container's internal scheduler. The scheduler is event-driven, not
fixed-interval: each run prints (with `--print-delay`) how long to sleep before
the next one, so the loop wakes only when there is something to do. The delay is
the time until the earliest unscored match's expected end (it must wake to score
each match as it finishes — the ranking updates per match, mid-phase), shortened
to a 1h retry while the current phase still has placeholder teams to resolve, and
capped so a clock skew never oversleeps. Between phases — every match scored and
the next bracket filled in — the loop idles at the cap (a few wake-ups a day)
instead of every 10 minutes.

A run where no match is past its expected end and the current phase has no
placeholder teams makes ZERO API calls. A match that has not finished yet stays
unscored and is re-checked on the next run.

Request economy: a fetch happens only when (a) a match is past its expected end
(due for scoring) or (b) the current phase still has placeholder teams that need
resolving — otherwise zero API calls. When anything triggers a fetch, ONE
`calendar/matches` request returns the whole tournament, so the single call both
scores every due match AND resolves placeholder teams for every unscored match
the bracket has filled in (team resolution is decoupled from scoring, so a
knockout phase shows its real teams during the prediction window, not ~3h after
each match kicks off). Scored matches are never queried again. Failures are
logged and retried next run; nothing is ever marked scored on failure.
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

# Event-driven sleep bounds for the scheduler loop (see module docstring).
MIN_DELAY = timezone.timedelta(minutes=10)  # floor; also the overdue re-check cadence
MAX_DELAY = timezone.timedelta(hours=6)  # cap so idle gaps still wake a few times/day
RESOLVE_RETRY = timezone.timedelta(hours=1)  # while current-phase teams stay placeholders


def expected_check_time(match):
    offset = KNOCKOUT_CHECK_OFFSET if match.is_knockout else GROUP_CHECK_OFFSET
    return match.starts_at + offset


def phase_has_placeholders():
    """True when the current phase still has an unresolved knockout slot.

    Only knockout matches ever carry placeholder teams (group teams are real
    from seed). Bounded to the current phase so far-future slots are ignored.
    """
    for m in current_phase_matches().select_related("home_team", "away_team"):
        if (
            not m.is_scored
            and m.external_id is not None
            and m.is_knockout
            and (m.home_team.external_id is None or m.away_team.external_id is None)
        ):
            return True
    return False


def compute_next_delay(now):
    """Seconds (as a timedelta) the scheduler should sleep before the next run.

    The next event is the earliest unscored match's expected end. A pending but
    overdue match (FIFA late) or no pending matches collapse to the bounds. While
    the current phase has placeholder teams, retry hourly so the bracket fills in
    promptly. Always clamped to [MIN_DELAY, MAX_DELAY].
    """
    pending = Match.objects.filter(is_scored=False, external_id__isnull=False)
    next_due = min(
        (expected_check_time(m) - now for m in pending), default=MAX_DELAY
    )
    if phase_has_placeholders():
        next_due = min(next_due, RESOLVE_RETRY)
    if next_due <= timezone.timedelta(0):
        return MIN_DELAY  # overdue/unscored: re-check on the floor cadence
    return max(MIN_DELAY, min(next_due, MAX_DELAY))


class Command(BaseCommand):
    help = "Fetch finished match results from api.fifa.com and score predictions."

    def add_arguments(self, parser):
        parser.add_argument(
            "--print-delay",
            action="store_true",
            help=(
                "After the run, print the seconds the scheduler should sleep "
                "before the next run (the only thing written to stdout). The "
                "container loop reads this to wake event-driven, not every 10 min."
            ),
        )

    def handle(self, *args, **options):
        self._run()
        if options.get("print_delay"):
            # The ONLY stdout output in this mode: a bare integer the loop reads.
            delay = compute_next_delay(timezone.now())
            self.stdout.write(str(int(delay.total_seconds())))

    def _run(self):
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
        if not due and not phase_has_placeholders():
            logger.info("Nothing due. No API calls made.")
            return

        client = FifaApiClient()
        try:
            feed = {m["external_id"]: m for m in normalize_matches(client.get_all_matches())}
        except FifaApiError as exc:
            # Retry on the next run; never mark anything scored here.
            logger.error("api.fifa.com fetch failed: %s", exc)
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
                    "Match %s not present in feed; retrying next run", match.external_id
                )
                continue
            scored += self._apply(match, normalized)

        logger.info(
            "Checked %d match(es), scored %d, resolved %d placeholder match(es).",
            len(due),
            scored,
            resolved,
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
