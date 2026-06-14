import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from pool.models import Team, Match, Prediction


@pytest.fixture
def client(db):
    from django.test import Client

    return Client()


@pytest.fixture
def teams(db):
    home = Team.objects.create(name="Brasil", flag="BR")
    away = Team.objects.create(name="Argentina", flag="AR")
    return home, away


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice", password="test123")


@pytest.fixture
def others(db):
    bob = User.objects.create_user(username="bob", password="test123")
    carol = User.objects.create_user(username="carol", password="test123")
    return bob, carol


@pytest.fixture
def auth_client(client, alice):
    client.login(username="alice", password="test123")
    return client


def url(match):
    return f"/matches/{match.id}/predictions/"


def make_match(teams, *, starts_at, phase="Group Stage - 1"):
    home, away = teams
    return Match.objects.create(
        home_team=home,
        away_team=away,
        stage="group",
        phase=phase,
        starts_at=starts_at,
    )


# ── Privacy guard ──────────────────────────────────────────────────────────


def test_hidden_before_kickoff(auth_client, teams, alice, others):
    """The core privacy invariant: an open (future, unscored) match never
    reveals predictions, even to a logged-in user."""
    bob, _ = others
    match = make_match(teams, starts_at=timezone.now() + timezone.timedelta(hours=2))
    Prediction.objects.create(user=bob, match=match, home_goals=1, away_goals=0)

    resp = auth_client.get(url(match))

    assert resp.status_code == 403
    assert resp.json()["ok"] is False
    assert "predictions" not in resp.json()


def test_hidden_when_locked_before_kickoff(auth_client, teams, others):
    """Locked state (past deadline, before kickoff) is also hidden — only
    live/finished reveal."""
    bob, _ = others
    # 10 min from now: past the 30-min deadline is false here; use a time that
    # is past the deadline but before kickoff.
    match = make_match(
        teams, starts_at=timezone.now() + timezone.timedelta(minutes=10)
    )
    Prediction.objects.create(user=bob, match=match, home_goals=1, away_goals=0)

    resp = auth_client.get(url(match))

    assert resp.status_code == 403


# ── Live (kicked off, not scored) ───────────────────────────────────────────


def test_live_reveals_others_without_result(auth_client, teams, alice, others):
    bob, carol = others
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=1))
    Prediction.objects.create(user=alice, match=match, home_goals=5, away_goals=5)
    Prediction.objects.create(user=bob, match=match, home_goals=2, away_goals=1)
    Prediction.objects.create(user=carol, match=match, home_goals=0, away_goals=0)

    resp = auth_client.get(url(match))
    data = resp.json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["is_finished"] is False
    usernames = {p["username"] for p in data["predictions"]}
    assert usernames == {"bob", "carol"}  # self (alice) excluded
    for p in data["predictions"]:
        assert p["result"] is None
        assert p["points"] is None


def test_self_is_excluded(auth_client, teams, alice):
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=1))
    Prediction.objects.create(user=alice, match=match, home_goals=1, away_goals=1)

    resp = auth_client.get(url(match))

    assert resp.status_code == 200
    assert resp.json()["predictions"] == []


# ── Finished (scored) ───────────────────────────────────────────────────────


def test_finished_includes_result_and_points(auth_client, teams, alice, others):
    bob, carol = others
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=3))
    Prediction.objects.create(user=alice, match=match, home_goals=0, away_goals=0)
    Prediction.objects.create(user=bob, match=match, home_goals=2, away_goals=1)
    Prediction.objects.create(user=carol, match=match, home_goals=1, away_goals=0)
    match.home_goals = 2
    match.away_goals = 1
    match.save()  # scores -> is_scored=True, predictions get result/points
    assert match.is_scored is True

    resp = auth_client.get(url(match))
    data = resp.json()

    assert resp.status_code == 200
    assert data["is_finished"] is True
    by_name = {p["username"]: p for p in data["predictions"]}
    assert set(by_name) == {"bob", "carol"}
    assert by_name["bob"]["result"] == "exact"
    assert by_name["bob"]["points"] == 10
    # Ordered by points desc: bob (exact) before carol.
    assert [p["username"] for p in data["predictions"]] == ["bob", "carol"]


# ── Misc / hardening ────────────────────────────────────────────────────────


def test_requires_authentication(client, teams, others):
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=1))
    resp = client.get(url(match))
    assert resp.status_code != 200  # redirected to login


def test_nonexistent_match_404(auth_client):
    resp = auth_client.get("/matches/999999/predictions/")
    assert resp.status_code == 404


def test_rejects_post(auth_client, teams):
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=1))
    resp = auth_client.post(url(match))
    assert resp.status_code == 405


def test_rate_limited(auth_client, teams):
    match = make_match(teams, starts_at=timezone.now() - timezone.timedelta(hours=1))
    last = None
    for _ in range(61):
        last = auth_client.get(url(match))
    assert last.status_code == 429
    assert last.json()["ok"] is False
