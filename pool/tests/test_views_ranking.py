from django.contrib.auth.models import User
from django.utils import timezone

from pool.models import Prediction


def finish(match, home, away):
    match.home_goals = home
    match.away_goals = away
    match.save()


def test_requires_login(client):
    resp = client.get("/ranking/")
    assert resp.status_code == 302
    assert "/login/" in resp.url


def test_ranking_context(auth_client, make_match, user):
    other = User.objects.create_user(username="joca", password="x")
    match = make_match(starts_at=timezone.now() - timezone.timedelta(days=1))
    Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=0)
    Prediction.objects.create(user=other, match=match, home_goals=0, away_goals=2)
    finish(match, 2, 0)

    resp = auth_client.get("/ranking/")

    ranking = resp.context["ranking"]
    assert [r.user.username for r in ranking] == ["rafael", "joca"]
    assert ranking[0].total_points == 10
    assert ranking[0].position == 1
    assert resp.context["total_matches"] == 1


def test_ranking_empty_state(auth_client):
    resp = auth_client.get("/ranking/")

    assert resp.status_code == 200
    assert resp.context["total_matches"] == 0
    assert len(resp.context["ranking"]) == 1  # only the logged-in user


def test_ranking_context_includes_phase_breakdown(auth_client, make_match, user):
    other = User.objects.create_user(username="joca", password="x")
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(days=1), phase="Group Stage - 1"
    )
    Prediction.objects.create(user=user, match=match, home_goals=2, away_goals=0)
    Prediction.objects.create(user=other, match=match, home_goals=0, away_goals=2)
    finish(match, 2, 0)

    resp = auth_client.get("/ranking/")

    assert resp.context["current_phase"] == "Group Stage - 1"
    phase_ranking = resp.context["phase_ranking"]
    assert [r.user.username for r in phase_ranking] == ["rafael", "joca"]
    assert phase_ranking[0].phase_points == 10
    assert phase_ranking[0].is_phase_leader is True
    # Default panel is the per-phase view, and the leader badge renders.
    assert b"Fase atual" in resp.content
    assert "🏆 liderando".encode() in resp.content


def test_phase_panel_renders_list_even_with_zero_points(auth_client, make_match, user):
    """Fase atual must list participants like Geral, never the old empty
    message — even when nobody has scored points in the focus phase yet."""
    other = User.objects.create_user(username="joca", password="x")
    match = make_match(
        starts_at=timezone.now() - timezone.timedelta(days=1), phase="Group Stage - 1"
    )
    # Both predict wrong -> phase points are 0 for everyone.
    Prediction.objects.create(user=user, match=match, home_goals=0, away_goals=2)
    Prediction.objects.create(user=other, match=match, home_goals=0, away_goals=3)
    finish(match, 2, 0)

    resp = auth_client.get("/ranking/")

    phase_ranking = resp.context["phase_ranking"]
    assert len(phase_ranking) == 2
    assert all(r.phase_points == 0 for r in phase_ranking)
    assert all(r.is_phase_leader is False for r in phase_ranking)
    # The old gate's empty message must be gone; the list renders instead.
    assert "Nenhum ponto".encode() not in resp.content


def test_ranking_view_never_aggregates(auth_client, monkeypatch):
    import pytest

    import pool.services.ranking as ranking_module

    monkeypatch.setattr(
        ranking_module,
        "compute_ranking",
        lambda: pytest.fail("ranking view must not aggregate at request time"),
    )

    resp = auth_client.get("/ranking/")
    assert resp.status_code == 200
