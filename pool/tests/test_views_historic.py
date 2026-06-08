from django.utils import timezone

from pool.models import Prediction


def finish(match, home, away):
    match.home_goals = home
    match.away_goals = away
    match.save()


def test_requires_login(client):
    resp = client.get("/historic/")
    assert resp.status_code == 302
    assert "/login/" in resp.url


def test_stats_and_entries(auth_client, make_match, user):
    now = timezone.now()
    exact = make_match(starts_at=now - timezone.timedelta(days=2), phase="Group Stage - 1")
    wrong = make_match(starts_at=now - timezone.timedelta(days=1), phase="Group Stage - 1")
    Prediction.objects.create(user=user, match=exact, home_goals=2, away_goals=0)
    Prediction.objects.create(user=user, match=wrong, home_goals=0, away_goals=2)
    finish(exact, 2, 0)
    finish(wrong, 2, 0)

    resp = auth_client.get("/historic/")

    stats = resp.context["stats"]
    assert stats["total_points"] == 10
    assert stats["exact_count"] == 1
    assert stats["total_predictions"] == 2
    assert len(resp.context["predictions"]) == 2


def test_skipped_match_appears_as_none(auth_client, make_match, user):
    match = make_match(starts_at=timezone.now() - timezone.timedelta(days=1))
    finish(match, 1, 0)  # scored, but user never predicted

    resp = auth_client.get("/historic/")

    entries = resp.context["predictions"]
    assert len(entries) == 1
    assert entries[0].result == "none"
    assert entries[0].match.id == match.id


def test_unscored_matches_not_listed(auth_client, make_match, user):
    match = make_match(starts_at=timezone.now() + timezone.timedelta(days=1))
    Prediction.objects.create(user=user, match=match, home_goals=1, away_goals=0)

    resp = auth_client.get("/historic/")

    assert len(resp.context["predictions"]) == 0
    # pending prediction still counts in the personal totals
    assert resp.context["stats"]["total_predictions"] == 1
    assert resp.context["stats"]["total_points"] == 0


def test_entries_ordered_newest_first(auth_client, make_match, user):
    now = timezone.now()
    older = make_match(starts_at=now - timezone.timedelta(days=3))
    newer = make_match(starts_at=now - timezone.timedelta(days=1))
    finish(older, 1, 0)
    finish(newer, 2, 2)

    resp = auth_client.get("/historic/")

    entries = resp.context["predictions"]
    assert [e.match.id for e in entries] == [newer.id, older.id]
