from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from pool.models import Match, Team
from pool.services.fifa_api import FifaApiError
from pool.tests.fifa_factories import fifa_match


@pytest.fixture
def mock_client():
    with mock.patch(
        "pool.management.commands.seed_world_cup.FifaApiClient"
    ) as cls:
        yield cls.return_value


def test_seed_creates_teams_and_matches(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(100, status=1, home="Brasil", away="Argentina")
    ]

    call_command("seed_world_cup")

    assert Team.objects.count() == 2
    brasil = Team.objects.get(external_id=10)
    assert brasil.name == "Brasil"
    assert brasil.flag == "BR"

    match = Match.objects.get(external_id=100)
    assert match.phase == "Group Stage - 1"
    assert match.stage == "group"
    assert match.api_status == "1"
    assert match.is_scored is False
    assert match.starts_at.isoformat() == "2026-06-11T19:00:00+00:00"


def test_seed_derives_knockout_phase(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(200, status=1, stage="Round of 16", group=None)
    ]

    call_command("seed_world_cup")

    match = Match.objects.get(external_id=200)
    assert match.stage == "round_of_16"
    assert match.is_knockout is True
    assert match.phase == "Round of 16"


def test_seed_group_matchday_from_kickoff_order(db, mock_client):
    # Same group, three matchdays out of order in the feed.
    mock_client.get_all_matches.return_value = [
        fifa_match(3, date="2026-06-21T19:00:00Z", match_number=53),
        fifa_match(1, date="2026-06-11T19:00:00Z", match_number=1),
        fifa_match(2, date="2026-06-16T19:00:00Z", match_number=25),
    ]

    call_command("seed_world_cup")

    assert Match.objects.get(external_id=1).phase == "Group Stage - 1"
    assert Match.objects.get(external_id=2).phase == "Group Stage - 2"
    assert Match.objects.get(external_id=3).phase == "Group Stage - 3"


def test_seed_creates_placeholder_team_for_knockout(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(
            200,
            status=1,
            stage="Round of 32",
            group=None,
            home_id=None,
            away_id=None,
            placeholder_a="1A",
            placeholder_b="2B",
        )
    ]

    call_command("seed_world_cup")

    home = Match.objects.get(external_id=200).home_team
    assert home.name == "1A"
    assert home.external_id is None
    assert home.flag == ""


def test_seed_is_idempotent(db, mock_client):
    mock_client.get_all_matches.return_value = [fifa_match(100, status=1)]

    call_command("seed_world_cup")
    call_command("seed_world_cup")

    assert Team.objects.count() == 2
    assert Match.objects.count() == 1


def test_seed_updates_existing_records(db, mock_client):
    mock_client.get_all_matches.return_value = [fifa_match(100, status=1, home="Brazil")]
    call_command("seed_world_cup")

    mock_client.get_all_matches.return_value = [fifa_match(100, status=1, home="Brasil")]
    call_command("seed_world_cup")

    assert Team.objects.get(external_id=10).name == "Brasil"


def test_seed_api_failure_writes_nothing(db, mock_client):
    mock_client.get_all_matches.side_effect = FifaApiError("down")

    with pytest.raises(CommandError):
        call_command("seed_world_cup")

    assert Team.objects.count() == 0
    assert Match.objects.count() == 0


def test_seed_empty_feed_writes_nothing(db, mock_client):
    mock_client.get_all_matches.return_value = []

    with pytest.raises(CommandError):
        call_command("seed_world_cup")

    assert Match.objects.count() == 0


def test_seed_dry_run_writes_nothing(db, mock_client):
    mock_client.get_all_matches.return_value = [fifa_match(100, status=1)]

    call_command("seed_world_cup", "--dry-run")

    assert Team.objects.count() == 0
    assert Match.objects.count() == 0


def test_seed_unknown_country_uses_empty_flag(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(100, status=1, home="Mystery", home_country="XYZ")
    ]

    call_command("seed_world_cup")

    assert Team.objects.get(external_id=10).flag == ""


def test_seed_uses_ptbr_team_names(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(
            100, status=1,
            home="South Africa", home_country="RSA",
            away="Czechia", away_country="CZE",
        )
    ]

    call_command("seed_world_cup")

    assert Team.objects.get(external_id=10).name == "África do Sul"
    assert Team.objects.get(external_id=26).name == "Tchéquia"


def test_seed_unknown_country_falls_back_to_feed_name(db, mock_client):
    mock_client.get_all_matches.return_value = [
        fifa_match(100, status=1, home="Mysteryland", home_country="XYZ")
    ]

    call_command("seed_world_cup")

    assert Team.objects.get(external_id=10).name == "Mysteryland"
