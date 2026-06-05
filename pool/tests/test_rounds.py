import pytest
from django.utils import timezone

from pool.services.rounds import (
    current_round_matches,
    future_round_matches,
    get_current_round,
    is_match_in_current_round,
    phase_from_round,
)


@pytest.mark.parametrize(
    "round_str, expected_phase",
    [
        ("Group Stage - 1", "group"),
        ("Group Stage - 2", "group"),
        ("Group Stage - 3", "group"),
        ("Round of 32", "round_of_32"),
        ("Round of 16", "round_of_16"),
        ("Quarter-finals", "quarter_final"),
        ("Quarterfinals", "quarter_final"),
        ("Semi-finals", "semi_final"),
        ("3rd Place Final", "third_place"),
        ("Third Place", "third_place"),
        ("Final", "final"),
    ],
)
def test_phase_from_round(round_str, expected_phase):
    assert phase_from_round(round_str) == expected_phase


def test_phase_from_round_unknown_falls_back_to_group():
    assert phase_from_round("Something Unexpected") == "group"


def test_get_current_round_none_when_empty(db):
    assert get_current_round() is None


def test_get_current_round_is_earliest_unscored(make_match):
    now = timezone.now()
    make_match(starts_at=now + timezone.timedelta(days=5), round="Group Stage - 2")
    make_match(starts_at=now + timezone.timedelta(days=1), round="Group Stage - 1")

    assert get_current_round() == "Group Stage - 1"


def test_current_round_advances_when_round_fully_scored(make_match):
    now = timezone.now()
    first = make_match(starts_at=now - timezone.timedelta(days=1), round="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=3), round="Group Stage - 2")

    assert get_current_round() == "Group Stage - 1"

    first.home_goals = 1
    first.away_goals = 0
    first.save()

    assert first.is_scored is True
    assert get_current_round() == "Group Stage - 2"


def test_multi_day_round_stays_current(make_match):
    now = timezone.now()
    make_match(starts_at=now, round="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=2), round="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=4), round="Group Stage - 2")

    current = current_round_matches()
    assert current.count() == 2
    assert all(m.round == "Group Stage - 1" for m in current)


def test_future_rounds_exclude_late_current_round_matches(make_match):
    now = timezone.now()
    make_match(starts_at=now, round="Group Stage - 1")
    late_current = make_match(
        starts_at=now + timezone.timedelta(days=2), round="Group Stage - 1"
    )
    future = make_match(
        starts_at=now + timezone.timedelta(days=4), round="Group Stage - 2"
    )

    future_ids = {m.id for m in future_round_matches()}
    assert future.id in future_ids
    assert late_current.id not in future_ids


def test_future_round_matches_empty_when_no_current(db):
    assert future_round_matches().count() == 0


def test_is_match_in_current_round(make_match):
    now = timezone.now()
    current = make_match(starts_at=now, round="Group Stage - 1")
    future = make_match(
        starts_at=now + timezone.timedelta(days=4), round="Group Stage - 2"
    )

    assert is_match_in_current_round(current) is True
    assert is_match_in_current_round(future) is False
