from unittest import mock

import pytest
from django.core.management import CommandError, call_command

from pool.models import Match, Team
from pool.services.api_football import ApiFootballError


def team_payload(team_id, name, code):
    return {"team": {"id": team_id, "name": name, "code": code}}


def fixture_payload(fixture_id, home_id, away_id, round_str, date="2026-06-11T20:00:00+00:00"):
    return {
        "fixture": {
            "id": fixture_id,
            "date": date,
            "status": {"short": "NS"},
        },
        "league": {"round": round_str},
        "teams": {
            "home": {"id": home_id, "name": f"Team {home_id}", "code": "BRA"},
            "away": {"id": away_id, "name": f"Team {away_id}", "code": "ARG"},
        },
    }


@pytest.fixture
def mock_client():
    with mock.patch(
        "pool.management.commands.seed_world_cup.ApiFootballClient"
    ) as cls:
        yield cls.return_value


def test_seed_creates_teams_and_matches(db, mock_client):
    mock_client.get_teams.return_value = [
        team_payload(10, "Brasil", "BRA"),
        team_payload(26, "Argentina", "ARG"),
    ]
    mock_client.get_fixtures.return_value = [
        fixture_payload(100, 10, 26, "Group Stage - 1")
    ]

    call_command("seed_world_cup")

    assert Team.objects.count() == 2
    brasil = Team.objects.get(external_id=10)
    assert brasil.name == "Brasil"
    assert brasil.flag == "BR"

    match = Match.objects.get(external_id=100)
    assert match.round == "Group Stage - 1"
    assert match.phase == "group"
    assert match.api_status == "NS"
    assert match.is_scored is False
    assert match.starts_at.isoformat() == "2026-06-11T20:00:00+00:00"


def test_seed_derives_knockout_phase(db, mock_client):
    mock_client.get_teams.return_value = []
    mock_client.get_fixtures.return_value = [
        fixture_payload(200, 10, 26, "Round of 16")
    ]

    call_command("seed_world_cup")

    match = Match.objects.get(external_id=200)
    assert match.phase == "round_of_16"
    assert match.is_knockout is True


def test_seed_is_idempotent(db, mock_client):
    mock_client.get_teams.return_value = [team_payload(10, "Brasil", "BRA")]
    mock_client.get_fixtures.return_value = [
        fixture_payload(100, 10, 26, "Group Stage - 1")
    ]

    call_command("seed_world_cup")
    call_command("seed_world_cup")

    assert Team.objects.count() == 2  # Brasil + Team 26 from fixture fallback
    assert Match.objects.count() == 1


def test_seed_updates_existing_records(db, mock_client):
    mock_client.get_teams.return_value = [team_payload(10, "Brazil", "BRA")]
    mock_client.get_fixtures.return_value = []
    call_command("seed_world_cup")

    mock_client.get_teams.return_value = [team_payload(10, "Brasil", "BRA")]
    call_command("seed_world_cup")

    assert Team.objects.get(external_id=10).name == "Brasil"


def test_seed_api_failure_writes_nothing(db, mock_client):
    mock_client.get_teams.side_effect = ApiFootballError("down")

    with pytest.raises(CommandError):
        call_command("seed_world_cup")

    assert Team.objects.count() == 0
    assert Match.objects.count() == 0


def test_seed_dry_run_writes_nothing(db, mock_client):
    mock_client.get_teams.return_value = [team_payload(10, "Brasil", "BRA")]
    mock_client.get_fixtures.return_value = [
        fixture_payload(100, 10, 26, "Group Stage - 1")
    ]

    call_command("seed_world_cup", "--dry-run")

    assert Team.objects.count() == 0
    assert Match.objects.count() == 0


def test_seed_unknown_team_code_uses_prefix(db, mock_client):
    mock_client.get_teams.return_value = [team_payload(99, "Mystery", "XYZ")]
    mock_client.get_fixtures.return_value = []

    call_command("seed_world_cup")

    assert Team.objects.get(external_id=99).flag == "XY"


def test_seed_missing_team_code_uses_empty_flag(db, mock_client):
    mock_client.get_teams.return_value = [{"team": {"id": 99, "name": "Mystery"}}]
    mock_client.get_fixtures.return_value = []

    call_command("seed_world_cup")

    assert Team.objects.get(external_id=99).flag == ""
