import pytest
from django.contrib.auth.models import User
from pool.models import Team, Match, Prediction
from django.utils import timezone


@pytest.fixture
def teams(db):
    home = Team.objects.create(name="Brasil", flag="BR")
    away = Team.objects.create(name="Argentina", flag="AR")

    return home, away


@pytest.fixture
def match(db, teams):
    home, away = teams
    return Match.objects.create(
        home_team=home,
        away_team=away,
        phase="group",
        starts_at=timezone.now() + timezone.timedelta(hours=2),
    )


@pytest.fixture
def user(db):
    return User.objects.create_user(username="Rafael", password="test123")


@pytest.fixture
def user2(db):
    return User.objects.create_user(username="Joca", password="test123")


@pytest.fixture
def user3(db):
    return User.objects.create_user(username="Lima", password="test123")


@pytest.mark.parametrize(
    "pred_home, pred_away, result_home, result_away, expected_points, expected_result",
    [
        (2, 1, 2, 1, 10, "exact"),
        (3, 1, 2, 0, 7, "partial"),
        (2, 0, 1, 0, 5, "partial"),
        (1, 1, 0, 0, 5, "partial"),
        (2, 0, 0, 1, 0, "wrong"),
        (0, 0, 0, 0, 10, "exact"),
    ],
)
def test_calculate_points_when_result_is_added(
    match,
    user,
    pred_home,
    pred_away,
    result_home,
    result_away,
    expected_points,
    expected_result,
):
    prediction = Prediction.objects.create(
        user=user,
        match=match,
        home_goals=pred_home,
        away_goals=pred_away,
    )

    match.home_goals = result_home
    match.away_goals = result_away
    match.save()

    prediction.refresh_from_db()

    assert prediction.points == expected_points
    assert prediction.result == expected_result


def test_calculate_multiple_user_points_when_result_is_added(
    match,
    user,
    user2,
    user3,
):
    pred1 = Prediction.objects.create(
        user=user,
        match=match,
        home_goals=2,
        away_goals=1,
    )

    pred2 = Prediction.objects.create(
        user=user2,
        match=match,
        home_goals=3,
        away_goals=0,
    )

    pred3 = Prediction.objects.create(
        user=user3,
        match=match,
        home_goals=0,
        away_goals=1,
    )

    match.home_goals = 2
    match.away_goals = 1
    match.save()

    pred1.refresh_from_db()
    pred2.refresh_from_db()
    pred3.refresh_from_db()

    assert pred1.points == 10 and pred1.result == "exact"
    assert pred2.points == 5 and pred2.result == "partial"
    assert pred3.points == 0 and pred3.result == "wrong"


def test_not_calculate_points(
    match,
    user,
):
    prediction = Prediction.objects.create(
        user=user,
        match=match,
        home_goals=2,
        away_goals=1,
    )

    match.home_goals = 2
    match.away_goals = 1

    prediction.refresh_from_db()

    assert prediction.points == None
    assert prediction.result == None


def test_no_predictions_does_not_break(match):
    match.home_goals = 2
    match.away_goals = 1
    match.save()
