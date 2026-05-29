from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from pool.models import Team, Match, Prediction

# Freeze "now" to a fixed mid-day instant so +/- hour offsets stay on the same
# local calendar date (the view filters today's matches by local date).
FROZEN_NOW = datetime(2026, 6, 15, 15, 0, tzinfo=dt_timezone.utc)  # 12:00 in America/Sao_Paulo


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: FROZEN_NOW)


@pytest.fixture
def client(db):
    return Client()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="rafael", password="test123")


@pytest.fixture
def auth_client(client, user):
    client.login(username="rafael", password="test123")
    return client


@pytest.fixture
def teams(db):
    home = Team.objects.create(name="Brasil", flag="BR")
    away = Team.objects.create(name="Argentina", flag="AR")
    return home, away


def make_match(teams, starts_at, phase="group"):
    home, away = teams
    return Match.objects.create(
        home_team=home, away_team=away, phase=phase, starts_at=starts_at
    )


def find(matches, match_id):
    return next(m for m in matches if m.id == match_id)


def test_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/" in resp.url


def test_open_match_is_today_and_open(auth_client, teams):
    match = make_match(teams, timezone.now() + timezone.timedelta(hours=2))

    resp = auth_client.get("/")

    today = resp.context["today_matches"]
    assert find(today, match.id).status == "open"


def test_match_with_prediction_is_predicted(auth_client, teams, user):
    match = make_match(teams, timezone.now() + timezone.timedelta(hours=2))
    Prediction.objects.create(user=user, match=match, home_goals=1, away_goals=0)

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).status == "predicted"


def test_match_past_deadline_is_locked(auth_client, teams):
    # Started an hour ago: still today, but the 30-min deadline has passed.
    match = make_match(teams, timezone.now() - timezone.timedelta(hours=1))

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).status == "locked"


def test_upcoming_matches_separated_from_today(auth_client, teams):
    today_match = make_match(teams, timezone.now() + timezone.timedelta(hours=2))
    future_match = make_match(teams, timezone.now() + timezone.timedelta(days=3))

    resp = auth_client.get("/")

    today_ids = {m.id for m in resp.context["today_matches"]}
    upcoming_ids = {m.id for m in resp.context["upcoming_matches"]}
    assert today_match.id in today_ids
    assert future_match.id in upcoming_ids
    assert today_match.id not in upcoming_ids


def test_knockout_phase_flag(auth_client, teams):
    match = make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), phase="round_of_32"
    )

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).is_knockout is True
