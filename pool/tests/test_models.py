import pytest
from django.db import IntegrityError
from django.utils import timezone

from pool.models import Prediction, RankingEntry, RoundWinner


def test_prediction_deadline_is_30_minutes_before_start(make_match):
    starts_at = timezone.now() + timezone.timedelta(hours=5)
    match = make_match(starts_at=starts_at)

    assert match.prediction_deadline == starts_at - timezone.timedelta(minutes=30)


def test_prediction_timestamps_are_set(make_match, user):
    match = make_match()
    prediction = Prediction.objects.create(
        user=user, match=match, home_goals=1, away_goals=0
    )

    assert prediction.created_at is not None
    assert prediction.updated_at is not None


def test_prediction_updated_at_changes_on_save(make_match, user):
    match = make_match()
    prediction = Prediction.objects.create(
        user=user, match=match, home_goals=1, away_goals=0
    )
    first = prediction.updated_at

    prediction.home_goals = 2
    prediction.save()
    prediction.refresh_from_db()

    assert prediction.updated_at >= first


def test_round_winner_unique_per_round_and_user(db, user):
    RoundWinner.objects.create(round="Group Stage - 1", user=user, points=10)

    with pytest.raises(IntegrityError):
        RoundWinner.objects.create(round="Group Stage - 1", user=user, points=12)


def test_round_winner_allows_multiple_users_same_round(db, user, django_user_model):
    other = django_user_model.objects.create_user(username="joca", password="x")
    RoundWinner.objects.create(round="Group Stage - 1", user=user, points=0)
    RoundWinner.objects.create(round="Group Stage - 1", user=other, points=0)

    assert RoundWinner.objects.filter(round="Group Stage - 1").count() == 2


def test_match_defaults(make_match):
    match = make_match()

    assert match.is_scored is False
    assert match.api_status == "NS"
    assert match.round == ""


def test_str_representations(make_match, user):
    match = make_match()
    prediction = Prediction.objects.create(
        user=user, match=match, home_goals=1, away_goals=0
    )
    winner = RoundWinner.objects.create(round="Group Stage - 1", user=user, points=10)
    entry = RankingEntry.objects.create(user=user, position=1, total_points=10)

    assert "Brasil" in str(match.home_team)
    assert "Brasil" in str(match)
    assert "1×0" in str(prediction)
    assert "10 pts" in str(winner)
    assert str(entry).startswith("#1")
