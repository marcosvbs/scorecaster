import pytest
from django.contrib.auth.models import User
from django.utils import timezone
from pool.models import Team, Match, Prediction


@pytest.fixture
def client(db):
    from django.test import Client

    return Client()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="rafael", password="test123")


@pytest.fixture
def teams(db):
    home = Team.objects.create(name="Brasil", flag="BR")
    away = Team.objects.create(name="Argentina", flag="AR")
    return home, away


@pytest.fixture
def open_match(db, teams):
    home, away = teams
    return Match.objects.create(
        home_team=home,
        away_team=away,
        phase="group",
        starts_at=timezone.now() + timezone.timedelta(hours=2),
    )


@pytest.fixture
def locked_match(db, teams):
    home, away = teams
    return Match.objects.create(
        home_team=home,
        away_team=away,
        phase="group",
        starts_at=timezone.now() - timezone.timedelta(hours=1),
    )


@pytest.fixture
def auth_client(client, user):
    client.login(username="rafael", password="test123")
    return client


def post(client, data):
    return client.post("/predictions/save/", data, content_type="application/json")


def test_creates_prediction(auth_client, open_match):
    resp = post(
        auth_client, {"match_id": open_match.id, "home_goals": 2, "away_goals": 1}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert Prediction.objects.count() == 1


def test_updates_existing_prediction(auth_client, open_match, user):
    Prediction.objects.create(user=user, match=open_match, home_goals=0, away_goals=0)
    post(auth_client, {"match_id": open_match.id, "home_goals": 3, "away_goals": 2})
    assert Prediction.objects.count() == 1
    assert Prediction.objects.first().home_goals == 3


def test_rejects_locked_match(auth_client, locked_match):
    resp = post(
        auth_client, {"match_id": locked_match.id, "home_goals": 1, "away_goals": 0}
    )
    assert resp.json()["ok"] is False
    assert Prediction.objects.count() == 0


def test_rejects_goals_above_99(auth_client, open_match):
    resp = post(
        auth_client, {"match_id": open_match.id, "home_goals": 100, "away_goals": 0}
    )
    assert resp.json()["ok"] is False


def test_rejects_negative_goals(auth_client, open_match):
    resp = post(
        auth_client, {"match_id": open_match.id, "home_goals": -1, "away_goals": 0}
    )
    assert resp.json()["ok"] is False


def test_rejects_missing_fields(auth_client, open_match):
    resp = post(auth_client, {"match_id": open_match.id})
    assert resp.json()["ok"] is False


def test_rejects_unauthenticated(client, open_match):
    resp = post(client, {"match_id": open_match.id, "home_goals": 1, "away_goals": 0})
    assert resp.status_code != 200


def test_rejects_nonexistent_match(auth_client):
    resp = post(auth_client, {"match_id": 9999, "home_goals": 1, "away_goals": 0})
    assert resp.status_code == 404


def test_rejects_get_request(auth_client, open_match):
    resp = auth_client.get("/predictions/save/")
    assert resp.status_code == 405


def test_accepts_zero_goals(auth_client, open_match):
    resp = post(
        auth_client, {"match_id": open_match.id, "home_goals": 0, "away_goals": 0}
    )
    assert resp.json()["ok"] is True


def test_accepts_max_goals(auth_client, open_match):
    resp = post(
        auth_client, {"match_id": open_match.id, "home_goals": 99, "away_goals": 99}
    )
    assert resp.json()["ok"] is True


def test_rejects_malformed_json(auth_client, open_match):
    resp = auth_client.post(
        "/predictions/save/", data="this is not json", content_type="application/json"
    )
    assert resp.status_code == 400
