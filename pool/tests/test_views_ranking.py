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
