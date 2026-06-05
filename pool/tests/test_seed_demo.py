import pytest
from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.utils import timezone

from pool.models import Match, Prediction, RoundWinner, Team
from pool.services.rounds import get_current_round


def test_seed_demo_creates_full_scenario(db):
    call_command("seed_demo")

    assert Team.objects.count() == 8
    assert User.objects.filter(username__in=["ana", "bruno", "carla"]).count() == 3
    assert Match.objects.count() == 8

    # closed round scored with ana as winner
    closed = Match.objects.filter(round="Group Stage - 1")
    assert all(m.is_scored for m in closed)
    winner = RoundWinner.objects.get(round="Group Stage - 1")
    assert winner.user.username == "ana"
    assert winner.points == 15

    # current round is Group Stage - 2 with one locked match
    assert get_current_round() == "Group Stage - 2"
    now = timezone.now()
    current = Match.objects.filter(round="Group Stage - 2")
    assert any(m.prediction_deadline <= now for m in current)
    assert any(m.prediction_deadline > now for m in current)

    # future rounds present, knockout included
    assert Match.objects.filter(round="Round of 16", phase="round_of_16").exists()


def test_seed_demo_refuses_to_overwrite(db):
    call_command("seed_demo")

    with pytest.raises(CommandError):
        call_command("seed_demo")


def test_seed_demo_reset_wipes_and_reseeds(db):
    call_command("seed_demo")
    call_command("seed_demo", "--reset")

    assert Match.objects.count() == 8
    assert Team.objects.count() == 8
    assert RoundWinner.objects.count() == 1
    assert Prediction.objects.count() == 6


def test_seed_demo_users_can_login(client):
    call_command("seed_demo")

    assert client.login(username="ana", password="demo123") is True
