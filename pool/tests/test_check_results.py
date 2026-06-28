from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from pool.management.commands.check_results import (
    MAX_DELAY,
    MIN_DELAY,
    RESOLVE_RETRY,
    compute_next_delay,
)
from pool.models import Match, Prediction, PhaseWinner, Team
from pool.services.fifa_api import FifaApiError
from pool.tests.fifa_factories import fifa_match


@pytest.fixture
def mock_client():
    with mock.patch(
        "pool.management.commands.check_results.FifaApiClient"
    ) as cls:
        yield cls.return_value


def test_noop_when_nothing_due(make_match, mock_client):
    # Started 10 minutes ago: well before the ~1h50 expected end.
    make_match(
        starts_at=timezone.now() - timezone.timedelta(minutes=10), external_id=100
    )

    call_command("check_results")

    mock_client.get_all_matches.assert_not_called()


def test_scored_match_never_queried(make_match, mock_client):
    make_match(
        starts_at=timezone.now() - timezone.timedelta(days=2),
        external_id=100,
        is_scored=True,
    )

    call_command("check_results")

    mock_client.get_all_matches.assert_not_called()


def test_finished_match_is_scored(make_match, mock_client, user):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        phase="Group Stage - 1",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_all_matches.return_value = [fifa_match(100, home_score=2, away_score=1)]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert match.home_goals == 2 and match.away_goals == 1
    assert match.api_status == "0"
    assert match.is_scored is True
    assert pred.points == 10 and pred.result == "exact"
    assert PhaseWinner.objects.filter(phase="Group Stage - 1").count() == 1


def test_single_call_covers_all_due_matches(make_match, mock_client):
    base = timezone.now() - timezone.timedelta(hours=5)
    make_match(starts_at=base, external_id=100)
    make_match(starts_at=base + timezone.timedelta(hours=1), external_id=101)
    mock_client.get_all_matches.return_value = [fifa_match(100), fifa_match(101)]

    call_command("check_results")

    assert mock_client.get_all_matches.call_count == 1


def test_knockout_waits_longer(make_match, teams, mock_client):
    # 2h after start: group game would be due, knockout (2h45) is not.
    home, away = teams
    Team.objects.filter(pk=home.pk).update(external_id=10)  # real teams, not slots
    Team.objects.filter(pk=away.pk).update(external_id=26)
    make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=2),
        external_id=100,
        stage="round_of_16",
        phase="Round of 16",
    )

    call_command("check_results")

    mock_client.get_all_matches.assert_not_called()


def test_unfinished_match_stays_unscored(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    # Status 1 = not finished, even though a (live) score is present.
    mock_client.get_all_matches.return_value = [
        fifa_match(100, status=1, home_score=1, away_score=0)
    ]

    call_command("check_results")

    match.refresh_from_db()
    assert match.is_scored is False
    assert match.api_status == "1"
    assert match.home_goals is None  # partial score never written


def test_api_failure_is_resilient(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    mock_client.get_all_matches.side_effect = FifaApiError("boom")

    call_command("check_results")  # must not raise

    match.refresh_from_db()
    assert match.is_scored is False  # retried on the next tick


def test_match_missing_from_feed_is_skipped(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    mock_client.get_all_matches.return_value = []  # feed omitted the match

    call_command("check_results")

    match.refresh_from_db()
    assert match.is_scored is False


def test_rerun_is_idempotent(make_match, mock_client, user):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        phase="Group Stage - 1",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_all_matches.return_value = [fifa_match(100)]

    call_command("check_results")
    call_command("check_results")  # second tick: match scored, not pending

    assert mock_client.get_all_matches.call_count == 1
    pred.refresh_from_db()
    assert pred.points == 10
    assert PhaseWinner.objects.count() == 1


def test_scores_even_when_goals_already_filled(make_match, mock_client, user):
    """Admin pre-filled the score but didn't trigger scoring; the feed confirms."""
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        home_goals=2,
        away_goals=1,
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_all_matches.return_value = [fifa_match(100, home_score=2, away_score=1)]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert match.is_scored is True
    assert pred.points == 10


def test_penalties_score_as_draw(make_match, mock_client, user):
    """1x1 after extra time decided on penalties scores as a 1x1 draw: the
    HomeTeamScore/AwayTeamScore fields exclude the shootout."""
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=4),
        external_id=100,
        stage="round_of_16",
        phase="Round of 16",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=0, away_goals=0)
    mock_client.get_all_matches.return_value = [
        fifa_match(
            100,
            stage="Round of 16",
            group=None,
            home_score=1,
            away_score=1,
            home_penalty=4,
            away_penalty=3,
        )
    ]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert (match.home_goals, match.away_goals) == (1, 1)
    assert pred.points == 5 and pred.result == "partial"  # correct draw


def test_knockout_placeholder_resolves_to_real_teams(make_match, mock_client):
    """A knockout match seeded with placeholder teams gets real teams once the
    feed fills the bracket in."""
    tbd_home = Team.objects.create(name="1A", flag="")
    tbd_away = Team.objects.create(name="2B", flag="")
    match = Match.objects.create(
        home_team=tbd_home,
        away_team=tbd_away,
        stage="round_of_32",
        phase="Round of 32",
        starts_at=timezone.now() - timezone.timedelta(hours=4),
        external_id=200,
    )
    mock_client.get_all_matches.return_value = [
        fifa_match(
            200,
            stage="Round of 32",
            group=None,
            home_id=10,
            away_id=26,
            home="Brasil",
            away="Argentina",
            home_score=3,
            away_score=0,
        )
    ]

    call_command("check_results")

    match.refresh_from_db()
    assert match.home_team.external_id == 10
    assert match.away_team.external_id == 26
    assert match.is_scored is True


def test_next_delay_caps_when_idle(db):
    """No pending matches: sleep at the cap, not on a busy 10-min loop."""
    assert compute_next_delay(timezone.now()) == MAX_DELAY


def test_next_delay_caps_for_far_future_match(make_match):
    make_match(starts_at=timezone.now() + timezone.timedelta(days=3), external_id=100)
    assert compute_next_delay(timezone.now()) == MAX_DELAY


def test_next_delay_floors_for_overdue_unscored_match(make_match):
    # Past its expected end but still unscored (FIFA late): re-check on the floor.
    make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=5), external_id=100
    )
    assert compute_next_delay(timezone.now()) == MIN_DELAY


def test_next_delay_retries_hourly_while_placeholders_unresolved(db):
    tbd_home = Team.objects.create(name="1F", flag="")
    tbd_away = Team.objects.create(name="2C", flag="")
    Match.objects.create(
        home_team=tbd_home,
        away_team=tbd_away,
        stage="round_of_32",
        phase="Round of 32",
        starts_at=timezone.now() + timezone.timedelta(days=2),  # not due
        external_id=200,
    )
    assert compute_next_delay(timezone.now()) == RESOLVE_RETRY


def test_print_delay_emits_bare_integer(make_match, mock_client):
    make_match(starts_at=timezone.now() + timezone.timedelta(days=3), external_id=100)
    out = StringIO()

    call_command("check_results", "--print-delay", stdout=out)

    assert out.getvalue().strip().isdigit()
    mock_client.get_all_matches.assert_not_called()  # nothing due, no API call


def test_current_phase_placeholder_resolves_before_kickoff(db, mock_client):
    """Current-phase knockout match still showing slot codes resolves its real
    teams even though it is not yet due for scoring (kickoff in the future)."""
    tbd_home = Team.objects.create(name="1F", flag="")
    tbd_away = Team.objects.create(name="2C", flag="")
    match = Match.objects.create(
        home_team=tbd_home,
        away_team=tbd_away,
        stage="round_of_32",
        phase="Round of 32",
        starts_at=timezone.now() + timezone.timedelta(hours=10),  # not due
        external_id=200,
    )
    mock_client.get_all_matches.return_value = [
        fifa_match(
            200,
            status=0,
            stage="Round of 32",
            group=None,
            home_id=10,
            away_id=26,
            home="Brasil",
            away="Argentina",
            home_score=None,
            away_score=None,
        )
    ]

    call_command("check_results")

    assert mock_client.get_all_matches.call_count == 1
    match.refresh_from_db()
    assert match.home_team.external_id == 10
    assert match.away_team.external_id == 26
    assert match.is_scored is False  # resolution must not score a future match


def test_no_fetch_when_current_phase_already_resolved(db, mock_client):
    """Nothing due and the current phase already has real teams: zero API calls."""
    home = Team.objects.create(name="Brasil", flag="BR", external_id=10)
    away = Team.objects.create(name="Argentina", flag="AR", external_id=26)
    Match.objects.create(
        home_team=home,
        away_team=away,
        stage="round_of_32",
        phase="Round of 32",
        starts_at=timezone.now() + timezone.timedelta(hours=10),  # not due
        external_id=200,
    )

    call_command("check_results")

    mock_client.get_all_matches.assert_not_called()
