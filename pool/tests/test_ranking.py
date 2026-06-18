import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from pool.models import Prediction, RankingEntry
from pool.services.ranking import (
    compute_ranking,
    get_phase_ranking,
    get_ranking,
    rebuild_ranking_snapshot,
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


def test_empty_ranking_lists_all_users_with_zero(users):
    rows = compute_ranking()

    assert len(rows) == 3
    assert all(r.total_points == 0 for r in rows)
    assert [r.position for r in rows] == [1, 2, 3]


def test_scored_matches_count_live_mid_phase(make_match, users):
    now = timezone.now()
    closed = make_match(starts_at=now - timezone.timedelta(days=2), phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=closed, home_goals=2, away_goals=0)
    finish(closed, 2, 0)  # ana +10

    in_progress = make_match(starts_at=now, phase="Group Stage - 2")
    pending = make_match(
        starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 2"
    )
    Prediction.objects.create(
        user=users[1], match=in_progress, home_goals=1, away_goals=0
    )
    finish(in_progress, 1, 0)  # bruno +10 immediately, even though phase 2 is open

    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["ana"].total_points == 10
    assert rows["bruno"].total_points == 10  # live: counts before phase 2 closes

    finish(pending, 0, 0)  # phase 2 fully scored, no extra points for bruno
    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["bruno"].total_points == 10


def test_ordering_and_positions(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)  # exact
    Prediction.objects.create(user=users[1], match=match, home_goals=1, away_goals=0)  # partial
    Prediction.objects.create(user=users[2], match=match, home_goals=0, away_goals=2)  # wrong
    finish(match, 2, 0)

    rows = compute_ranking()
    assert [r.user.username for r in rows] == ["ana", "bruno", "carla"]
    assert [r.position for r in rows] == [1, 2, 3]
    assert [r.total_points for r in rows] == [10, 5, 0]


def test_tiebreak_more_exact_hits(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    second = make_match(
        starts_at=now + timezone.timedelta(hours=5), phase="Group Stage - 1"
    )
    # ana: exact (10) + wrong (0). bruno: partial diff (7) + wrong... use:
    # ana = exact 10; bruno = partial 5 + partial 5 -> both 10 points.
    Prediction.objects.create(user=users[0], match=first, home_goals=3, away_goals=0)
    Prediction.objects.create(user=users[1], match=first, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[1], match=second, home_goals=1, away_goals=0)
    finish(first, 3, 0)  # ana exact 10, bruno partial 5
    finish(second, 4, 0)  # bruno partial 5 -> both at 10

    rows = compute_ranking()
    ana, bruno = rows[0], rows[1]
    assert ana.user.username == "ana"
    assert ana.total_points == bruno.total_points == 10
    assert ana.exact_count > bruno.exact_count


def test_tiebreak_fewer_skipped(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    second = make_match(
        starts_at=now + timezone.timedelta(hours=5), phase="Group Stage - 1"
    )
    # Same points, same exact, same winner hits; carla skips one match.
    Prediction.objects.create(user=users[0], match=first, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[0], match=second, home_goals=0, away_goals=2)
    Prediction.objects.create(user=users[2], match=first, home_goals=1, away_goals=0)
    finish(first, 2, 0)  # both partial 5
    finish(second, 1, 1)  # ana wrong 0

    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["ana"].total_points == rows["carla"].total_points == 5
    assert rows["ana"].skipped == 0
    assert rows["carla"].skipped == 1
    assert rows["ana"].position < rows["carla"].position


def test_user_without_predictions_has_high_skip_count(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=1, away_goals=0)
    finish(match, 1, 0)

    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["bruno"].skipped == 1
    assert rows["bruno"].total_points == 0


# ── Pre-computed snapshot (RankingEntry) ──


def test_phase_close_rebuilds_snapshot(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)

    assert RankingEntry.objects.count() == 0
    finish(match, 2, 0)  # closes the phase -> snapshot written

    entries = list(RankingEntry.objects.all())
    assert len(entries) == 3
    assert entries[0].user == users[0]
    assert entries[0].total_points == 10
    assert entries[0].position == 1


def test_mid_phase_score_rebuilds_snapshot(make_match, users):
    """Scoring a single match rebuilds the snapshot, even while the phase
    still has pending matches (live per-match ranking)."""
    now = timezone.now()
    scored = make_match(starts_at=now, phase="Group Stage - 1")
    make_match(
        starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 1"
    )  # pending -> phase stays open
    Prediction.objects.create(user=users[0], match=scored, home_goals=2, away_goals=0)

    finish(scored, 2, 0)  # phase not closed, but snapshot must update

    entry = RankingEntry.objects.get(user=users[0])
    assert entry.total_points == 10
    assert entry.position == 1


def test_correction_updates_snapshot(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[1], match=match, home_goals=0, away_goals=2)

    finish(match, 2, 0)
    assert RankingEntry.objects.get(position=1).user == users[0]

    finish(match, 0, 2)  # admin correction flips the result
    assert RankingEntry.objects.get(position=1).user == users[1]
    assert RankingEntry.objects.count() == 3  # no duplicates


def test_get_ranking_reads_snapshot_without_aggregating(make_match, users, monkeypatch):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)
    finish(match, 2, 0)

    import pool.services.ranking as ranking_module

    monkeypatch.setattr(
        ranking_module,
        "compute_ranking",
        lambda: pytest.fail("get_ranking must not aggregate"),
    )

    rows = get_ranking()
    assert rows[0].user == users[0]
    assert rows[0].total_points == 10


def test_get_ranking_appends_users_created_after_snapshot(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)
    finish(match, 2, 0)

    late = User.objects.create_user(username="zeca", password="x")

    rows = get_ranking()
    assert rows[-1].user == late
    assert rows[-1].total_points == 0
    assert rows[-1].position == 4


def test_get_ranking_empty_snapshot_lists_all_users_at_zero(users):
    rows = get_ranking()

    assert len(rows) == 3
    assert all(r.total_points == 0 for r in rows)
    assert [r.position for r in rows] == [1, 2, 3]


def test_rebuild_snapshot_is_idempotent(make_match, users):
    match = make_match(phase="Group Stage - 1")
    Prediction.objects.create(user=users[0], match=match, home_goals=2, away_goals=0)
    finish(match, 2, 0)

    rebuild_ranking_snapshot()
    rebuild_ranking_snapshot()

    assert RankingEntry.objects.count() == 3


# ── Focus-phase breakdown ──


def test_compute_ranking_phase_points_only_count_focus_phase(make_match, users):
    now = timezone.now()
    p1 = make_match(starts_at=now - timezone.timedelta(days=2), phase="Group Stage - 1")
    p2_scored = make_match(starts_at=now, phase="Group Stage - 2")
    make_match(
        starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 2"
    )  # pending -> phase 2 is the current (focus) phase
    Prediction.objects.create(user=users[0], match=p1, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[0], match=p2_scored, home_goals=1, away_goals=0)
    finish(p1, 2, 0)  # ana +10 (phase 1)
    finish(p2_scored, 1, 0)  # ana +10 (phase 2 — the focus phase)

    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["ana"].total_points == 20
    assert rows["ana"].phase == "Group Stage - 2"
    assert rows["ana"].phase_points == 10  # only the phase-2 match
    assert rows["ana"].phase_exact_count == 1


def test_focus_phase_falls_back_to_last_scored_after_close(make_match, users):
    """When the current phase has no scored match yet, the breakdown features
    the most recently scored phase instead of showing all zeros."""
    now = timezone.now()
    p1 = make_match(starts_at=now - timezone.timedelta(days=1), phase="Group Stage - 1")
    make_match(
        starts_at=now + timezone.timedelta(days=1), phase="Group Stage - 2"
    )  # current phase, nothing scored
    Prediction.objects.create(user=users[0], match=p1, home_goals=2, away_goals=0)
    finish(p1, 2, 0)  # phase 1 closes; current phase is now phase 2 (0 scored)

    rows = {r.user.username: r for r in compute_ranking()}
    assert rows["ana"].phase == "Group Stage - 1"
    assert rows["ana"].phase_points == 10


def test_get_phase_ranking_sorts_by_phase_points_and_flags_leader(make_match, users):
    now = timezone.now()
    first = make_match(starts_at=now, phase="Group Stage - 1")
    second = make_match(
        starts_at=now + timezone.timedelta(hours=5), phase="Group Stage - 1"
    )
    # carla wins the phase; bruno second; ana wrong.
    Prediction.objects.create(user=users[2], match=first, home_goals=2, away_goals=0)
    Prediction.objects.create(user=users[1], match=first, home_goals=1, away_goals=0)
    Prediction.objects.create(user=users[0], match=first, home_goals=0, away_goals=2)
    finish(first, 2, 0)  # carla +10, bruno +5, ana 0
    finish(second, 0, 0)  # phase closes

    phase_rows = get_phase_ranking()
    assert [r.user.username for r in phase_rows] == ["carla", "bruno", "ana"]
    assert [r.position for r in phase_rows] == [1, 2, 3]
    assert [r.phase_points for r in phase_rows] == [10, 5, 0]
    assert phase_rows[0].is_phase_leader is True
    assert phase_rows[1].is_phase_leader is False


def test_get_phase_ranking_no_leader_when_no_points(users):
    phase_rows = get_phase_ranking()
    assert len(phase_rows) == 3
    assert all(r.phase_points == 0 for r in phase_rows)
    assert all(r.is_phase_leader is False for r in phase_rows)
