"""Full-reset admin routine: wipe predictions + derived data, reopen matches."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from pool.models import Match, Prediction, RankingEntry, RoundWinner, Team
from pool.services.reset import full_reset


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="test123")


@pytest.fixture
def populated(db, user, make_match):
    """A scored match with a prediction plus derived ranking/winner rows."""
    match = make_match(round="Group Stage - 1", home_goals=2, away_goals=1)
    Match.objects.filter(pk=match.pk).update(is_scored=True, api_status="FT")
    Prediction.objects.create(
        user=user, match=match, home_goals=2, away_goals=1, points=10, result="exact"
    )
    RoundWinner.objects.create(
        round="Group Stage - 1", user=user, points=10, exact_count=1, partial_count=0
    )
    RankingEntry.objects.create(
        user=user, position=1, total_points=10, exact_count=1, winner_hit_count=1
    )
    return match


def test_full_reset_wipes_and_reopens(populated):
    counts = full_reset()

    assert Prediction.objects.count() == 0
    assert RoundWinner.objects.count() == 0
    assert RankingEntry.objects.count() == 0
    # Teams survive.
    assert Team.objects.count() == 2
    # Matches reopened, goals cleared.
    match = Match.objects.get(pk=populated.pk)
    assert match.home_goals is None and match.away_goals is None
    assert match.is_scored is False
    assert match.api_status == "NS"

    assert counts == {
        "predictions": 1,
        "round_winners": 1,
        "ranking_entries": 1,
        "matches": 1,
    }


def test_full_reset_is_idempotent_on_empty_db(db):
    assert full_reset() == {
        "predictions": 0,
        "round_winners": 0,
        "ranking_entries": 0,
        "matches": 0,
    }


def test_view_get_renders_confirm_for_superuser(client, superuser, populated):
    client.force_login(superuser)
    resp = client.get(reverse("admin:pool_prediction_full_reset"))
    assert resp.status_code == 200
    assert b"ZERAR" in resp.content
    # Nothing wiped by a GET.
    assert Prediction.objects.count() == 1


def test_view_post_with_correct_word_wipes(client, superuser, populated):
    client.force_login(superuser)
    resp = client.post(
        reverse("admin:pool_prediction_full_reset"), {"confirm": "ZERAR"}
    )
    assert resp.status_code == 302
    assert Prediction.objects.count() == 0
    assert Match.objects.filter(is_scored=True).count() == 0


def test_view_post_with_wrong_word_does_not_wipe(client, superuser, populated):
    client.force_login(superuser)
    resp = client.post(
        reverse("admin:pool_prediction_full_reset"), {"confirm": "nope"}
    )
    assert resp.status_code == 302
    assert Prediction.objects.count() == 1


def test_view_rejects_non_superuser(client, db, populated):
    staff = User.objects.create_user(
        username="staff", password="test123", is_staff=True
    )
    client.force_login(staff)
    resp = client.post(
        reverse("admin:pool_prediction_full_reset"), {"confirm": "ZERAR"}
    )
    # Redirected back, no wipe.
    assert resp.status_code == 302
    assert Prediction.objects.count() == 1
