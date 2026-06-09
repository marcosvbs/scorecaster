"""Admin test helper: simulate the first phase with random results."""

import pytest
from django.contrib.auth.models import User
from django.urls import reverse

from pool.models import Match, Prediction
from pool.services.simulate import simulate_first_phase


@pytest.fixture
def superuser(db):
    return User.objects.create_superuser(username="admin", password="test123")


@pytest.fixture
def two_phases(db, make_match):
    """One match in the first phase, one in a later phase (different starts)."""
    from django.utils import timezone

    now = timezone.now()
    first = make_match(
        starts_at=now - timezone.timedelta(days=2),
        phase="Group Stage - 1",
    )
    later = make_match(
        starts_at=now + timezone.timedelta(days=5),
        phase="Group Stage - 2",
    )
    return first, later


def test_simulates_only_first_phase(two_phases):
    first, later = two_phases

    result = simulate_first_phase()

    first.refresh_from_db()
    later.refresh_from_db()

    assert result == {"phase": "Group Stage - 1", "scored": 1, "skipped": 0}
    # First-phase match: scored with goals in range.
    assert first.is_scored is True
    assert 0 <= first.home_goals <= 5
    assert 0 <= first.away_goals <= 5
    # Later phase untouched.
    assert later.is_scored is False
    assert later.home_goals is None and later.away_goals is None


def test_skips_already_scored(two_phases):
    first, _ = two_phases
    Match.objects.filter(pk=first.pk).update(
        home_goals=2, away_goals=1, is_scored=True
    )

    result = simulate_first_phase()

    first.refresh_from_db()
    assert result == {"phase": "Group Stage - 1", "scored": 0, "skipped": 1}
    # Existing score untouched.
    assert first.home_goals == 2 and first.away_goals == 1


def test_empty_db_returns_zeros(db):
    assert simulate_first_phase() == {"phase": None, "scored": 0, "skipped": 0}


def test_scoring_cascade_runs(two_phases, user):
    """A prediction on a first-phase match gets points/result after simulate,
    proving Match.save()'s scoring pipeline fired."""
    first, _ = two_phases
    Prediction.objects.create(user=user, match=first, home_goals=1, away_goals=1)

    simulate_first_phase()

    pred = Prediction.objects.get(user=user, match=first)
    assert pred.result is not None
    assert pred.points is not None


def test_view_get_renders_confirm_for_superuser(client, superuser, two_phases):
    client.force_login(superuser)
    resp = client.get(reverse("admin:pool_match_simulate_first_phase"))
    assert resp.status_code == 200
    assert b"Group Stage - 1" in resp.content
    # Nothing scored by a GET.
    assert Match.objects.filter(is_scored=True).count() == 0


def test_view_post_simulates_first_phase(client, superuser, two_phases):
    client.force_login(superuser)
    resp = client.post(reverse("admin:pool_match_simulate_first_phase"))
    assert resp.status_code == 302
    first, later = two_phases
    first.refresh_from_db()
    later.refresh_from_db()
    assert first.is_scored is True
    assert later.is_scored is False


def test_view_rejects_non_superuser(client, db, two_phases):
    staff = User.objects.create_user(
        username="staff", password="test123", is_staff=True
    )
    client.force_login(staff)
    resp = client.post(reverse("admin:pool_match_simulate_first_phase"))
    assert resp.status_code == 302
    assert Match.objects.filter(is_scored=True).count() == 0
