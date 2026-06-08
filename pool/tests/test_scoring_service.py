import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from pool.models import Match, Prediction, PhaseWinner
from pool.services.scoring_service import (
    close_phase_if_complete,
    compute_phase_winners,
    score_match,
)


@pytest.fixture
def users(db):
    return [
        User.objects.create_user(username=name, password="x")
        for name in ["ana", "bruno", "carla"]
    ]


def finish(match, home, away):
    match.home_goals = home
    match.away_goals = away
    match.save()
    match.refresh_from_db()
    return match


def test_score_match_scores_predictions_and_marks_scored(make_match, users):
    match = make_match(phase="Group Stage - 1")
    pred = Prediction.objects.create(
        user=users[0], match=match, home_goals=2, away_goals=1
    )
    match.home_goals = 2
    match.away_goals = 1
    Match.objects.filter(pk=match.pk).update(home_goals=2, away_goals=1)

    score_match(match)

    pred.refresh_from_db()
    match.refresh_from_db()
    assert pred.points == 10 and pred.result == "exact"
    assert match.is_scored is True


def test_score_match_is_idempotent(make_match, users):
    match = make_match(phase="Group Stage - 1")
    pred = Prediction.objects.create(
        user=users[0], match=match, home_goals=1, away_goals=0
    )

    finish(match, 1, 0)
    score_match(match)  # second run
    score_match(match)  # third run

    pred.refresh_from_db()
    assert pred.points == 10 and pred.result == "exact"
    assert PhaseWinner.objects.filter(phase="Group Stage - 1").count() == 1


def test_phase_not_closed_while_matches_pending(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    make_match(starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=first, home_goals=1, away_goals=0)

    finish(first, 1, 0)

    assert PhaseWinner.objects.count() == 0


def test_phase_closes_when_last_match_scored(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    second = make_match(
        starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 1"
    )
    Prediction.objects.create(user=users[0], match=first, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[1], match=first, home_goals=0, away_goals=1)

    finish(first, 1, 0)
    finish(second, 2, 2)

    winners = PhaseWinner.objects.filter(phase="Group Stage - 1")
    assert winners.count() == 1
    assert winners.first().user == users[0]
    assert winners.first().points == 10


def test_close_phase_if_complete_noop_for_unknown_phase(db):
    assert close_phase_if_complete("Nope") is None


def test_winner_tiebreak_by_total_points(make_match, users):
    """Tied in the phase -> higher cumulative total wins (spec 7.2)."""
    now = timezone.now()
    # Round 1: ana gains 10, bruno 0 -> ana leads the overall ranking.
    r1 = make_match(starts_at=now - timezone.timedelta(days=3), phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=r1, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[1], match=r1, home_goals=0, away_goals=2)
    finish(r1, 2, 0)

    # Round 2: both score 5 (hit winner only) -> tie on phase points.
    r2 = make_match(starts_at=now, phase="Group Stage - 2")
    Prediction.objects.create(user=users[0], match=r2, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[1], match=r2, home_goals=2, away_goals=0)
    finish(r2, 3, 0)

    winners = PhaseWinner.objects.filter(phase="Group Stage - 2")
    assert winners.count() == 1
    assert winners.first().user == users[0]
    assert winners.first().points == 5


def test_multiple_winners_when_nobody_scored(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[1], match=match, home_goals=2, away_goals=0)

    finish(match, 0, 1)  # both wrong, 0 points each

    winners = PhaseWinner.objects.filter(phase="Group Stage - 1")
    assert winners.count() == 2
    assert {w.user for w in winners} == {users[0], users[1]}
    assert all(w.points == 0 for w in winners)


def test_no_winners_without_predictions(make_match):
    match = make_match(phase="Group Stage - 1")
    finish(match, 1, 0)

    assert compute_phase_winners("Group Stage - 1") == []
    assert PhaseWinner.objects.count() == 0


def test_admin_correction_updates_winner(make_match, users):
    """Manual result fix re-runs the pipeline and replaces a stale winner."""
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[1], match=match, home_goals=0, away_goals=2)

    finish(match, 2, 0)
    assert PhaseWinner.objects.get(phase="Group Stage - 1").user == users[0]

    finish(match, 0, 2)  # correction flips the result
    winners = PhaseWinner.objects.filter(phase="Group Stage - 1")
    assert winners.count() == 1
    assert winners.first().user == users[1]


def test_winner_counts_exact_and_partial(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    second = make_match(
        starts_at=now + timezone.timedelta(hours=5), phase="Group Stage - 1"
    )
    Prediction.objects.create(user=users[0], match=first, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[0], match=second, home_goals=1, away_goals=0)

    finish(first, 2, 0)  # exact
    finish(second, 3, 0)  # partial (winner only)

    winner = PhaseWinner.objects.get(phase="Group Stage - 1")
    assert winner.points == 15
    assert winner.exact_count == 1
    assert winner.partial_count == 1
