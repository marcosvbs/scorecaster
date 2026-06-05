from unittest import mock

import pytest
from django.core.management import call_command
from django.utils import timezone

from pool.models import Prediction, RoundWinner
from pool.services.api_football import ApiFootballError


def fixture_payload(external_id, status="FT", home=2, away=1):
    return {
        "fixture": {"id": external_id, "status": {"short": status}},
        "goals": {"home": home, "away": away},
    }


@pytest.fixture
def mock_client():
    with mock.patch(
        "pool.management.commands.check_results.ApiFootballClient"
    ) as cls:
        yield cls.return_value


def test_noop_when_nothing_due(make_match, mock_client):
    # Started 10 minutes ago: well before the ~1h50 expected end.
    make_match(
        starts_at=timezone.now() - timezone.timedelta(minutes=10), external_id=100
    )

    call_command("check_results")

    mock_client.get_fixtures_by_date.assert_not_called()


def test_scored_match_never_queried(make_match, mock_client):
    make_match(
        starts_at=timezone.now() - timezone.timedelta(days=2),
        external_id=100,
        is_scored=True,
    )

    call_command("check_results")

    mock_client.get_fixtures_by_date.assert_not_called()


def test_finished_match_is_scored(make_match, mock_client, user):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        round="Group Stage - 1",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_fixtures_by_date.return_value = [fixture_payload(100)]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert match.home_goals == 2 and match.away_goals == 1
    assert match.api_status == "FT"
    assert match.is_scored is True
    assert pred.points == 10 and pred.result == "exact"
    assert RoundWinner.objects.filter(round="Group Stage - 1").count() == 1


def test_requests_grouped_by_date(make_match, mock_client):
    same_day = timezone.now() - timezone.timedelta(hours=5)
    make_match(starts_at=same_day, external_id=100)
    make_match(starts_at=same_day + timezone.timedelta(hours=1), external_id=101)
    mock_client.get_fixtures_by_date.return_value = [
        fixture_payload(100),
        fixture_payload(101),
    ]

    call_command("check_results")

    assert mock_client.get_fixtures_by_date.call_count == 1


def test_knockout_waits_longer(make_match, mock_client):
    # 2h after start: group game would be due, knockout (2h45) is not.
    make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=2),
        external_id=100,
        phase="round_of_16",
        round="Round of 16",
    )

    call_command("check_results")

    mock_client.get_fixtures_by_date.assert_not_called()


def test_unfinished_match_stays_unscored(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    mock_client.get_fixtures_by_date.return_value = [
        fixture_payload(100, status="2H", home=1, away=0)
    ]

    call_command("check_results")

    match.refresh_from_db()
    assert match.is_scored is False
    assert match.api_status == "2H"
    assert match.home_goals is None  # partial score never written


def test_api_failure_is_resilient(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    mock_client.get_fixtures_by_date.side_effect = ApiFootballError("boom")

    call_command("check_results")  # must not raise

    match.refresh_from_db()
    assert match.is_scored is False  # retried on the next tick


def test_missing_fixture_in_response_is_skipped(make_match, mock_client):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3), external_id=100
    )
    mock_client.get_fixtures_by_date.return_value = []

    call_command("check_results")

    match.refresh_from_db()
    assert match.is_scored is False


def test_rerun_is_idempotent(make_match, mock_client, user):
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        round="Group Stage - 1",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_fixtures_by_date.return_value = [fixture_payload(100)]

    call_command("check_results")
    call_command("check_results")  # second tick: match scored, no new query

    assert mock_client.get_fixtures_by_date.call_count == 1
    pred.refresh_from_db()
    assert pred.points == 10
    assert RoundWinner.objects.count() == 1


def test_scores_even_when_goals_already_filled(make_match, mock_client, user):
    """Admin pre-filled the score but didn't trigger scoring; API confirms."""
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=3),
        external_id=100,
        home_goals=2,
        away_goals=1,
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=1)
    mock_client.get_fixtures_by_date.return_value = [fixture_payload(100)]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert match.is_scored is True
    assert pred.points == 10


def test_penalties_score_as_draw(make_match, mock_client, user):
    """1x1 after extra time decided on penalties scores as a 1x1 draw."""
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(hours=4),
        external_id=100,
        phase="round_of_16",
        round="Round of 16",
    )
    pred = Prediction.objects.create(user=user, match=match, home_goals=0, away_goals=0)
    mock_client.get_fixtures_by_date.return_value = [
        fixture_payload(100, status="PEN", home=1, away=1)
    ]

    call_command("check_results")

    match.refresh_from_db()
    pred.refresh_from_db()
    assert (match.home_goals, match.away_goals) == (1, 1)
    assert pred.points == 5 and pred.result == "partial"  # correct draw
