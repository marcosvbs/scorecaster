import pytest
from django.utils import timezone

from pool.services.phases import (
    current_phase_matches,
    future_phase_matches,
    get_current_phase,
    is_match_in_current_phase,
    stage_from_phase,
    phase_label,
)


def test_phase_label_group_includes_matchday():
    assert phase_label("Group Stage - 1") == "Fase de Grupos · 1ª Rodada"
    assert phase_label("Group Stage - 3") == "Fase de Grupos · 3ª Rodada"


def test_phase_label_knockout_uses_ptbr_phase():
    assert phase_label("Round of 16") == "Oitavas de Final"
    assert phase_label("Final") == "Final"


def test_phase_label_group_without_number_falls_back():
    assert phase_label("Group Stage") == "Fase de Grupos"


@pytest.mark.parametrize(
    "phase_str, expected_phase",
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
def test_stage_from_phase(phase_str, expected_phase):
    assert stage_from_phase(phase_str) == expected_phase


def test_stage_from_phase_unknown_falls_back_to_group():
    assert stage_from_phase("Something Unexpected") == "group"


def test_get_current_phase_none_when_empty(db):
    assert get_current_phase() is None


def test_get_current_phase_is_earliest_unscored(make_match):
    now = timezone.now()
    make_match(starts_at=now + timezone.timedelta(days=5), phase="Group Stage - 2")
    make_match(starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 1")

    assert get_current_phase() == "Group Stage - 1"


def test_current_phase_advances_when_phase_fully_scored(make_match):
    now = timezone.now()
    first = make_match(starts_at=now - timezone.timedelta(days=1), phase="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=3), phase="Group Stage - 2")

    assert get_current_phase() == "Group Stage - 1"

    first.home_goals = 1
    first.away_goals = 0
    first.save()

    assert first.is_scored is True
    assert get_current_phase() == "Group Stage - 2"


def test_multi_day_phase_stays_current(make_match):
    now = timezone.now()
    make_match(starts_at=now, phase="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=2), phase="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=4), phase="Group Stage - 2")

    current = current_phase_matches()
    assert current.count() == 2
    assert all(m.phase == "Group Stage - 1" for m in current)


def test_future_phases_exclude_late_current_phase_matches(make_match):
    now = timezone.now()
    make_match(starts_at=now, phase="Group Stage - 1")
    late_current = make_match(
        starts_at=now + timezone.timedelta(days=2), phase="Group Stage - 1"
    )
    future = make_match(
        starts_at=now + timezone.timedelta(days=4), phase="Group Stage - 2"
    )

    future_ids = {m.id for m in future_phase_matches()}
    assert future.id in future_ids
    assert late_current.id not in future_ids


def test_future_phase_matches_empty_when_no_current(db):
    assert future_phase_matches().count() == 0


def test_is_match_in_current_phase(make_match):
    now = timezone.now()
    current = make_match(starts_at=now, phase="Group Stage - 1")
    future = make_match(
        starts_at=now + timezone.timedelta(days=4), phase="Group Stage - 2"
    )

    assert is_match_in_current_phase(current) is True
    assert is_match_in_current_phase(future) is False
