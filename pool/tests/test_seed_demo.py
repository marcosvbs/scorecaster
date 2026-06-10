"""Demo-mode wiring: seed_demo snapshot, write block, one-click login gating."""

import json

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from pool.models import Match, Prediction, PhaseWinner, RankingEntry
from pool.services.phases import get_current_phase

PHASE_1 = "Group Stage - 1"
PHASE_2 = "Group Stage - 2"


@pytest.fixture
def seeded(db):
    call_command("seed_demo")


def test_seed_demo_builds_frozen_snapshot(seeded):
    # 5 fictional competitors.
    assert User.objects.count() == 5

    # Phase 1 fully scored, Phase 2 left open as the current phase.
    gs1 = Match.objects.filter(phase=PHASE_1)
    assert gs1.exists()
    assert gs1.filter(is_scored=False).count() == 0
    assert Match.objects.filter(phase=PHASE_2, is_scored=True).count() == 0
    assert get_current_phase() == PHASE_2

    # Derived data populated by the real scoring cascade.
    assert RankingEntry.objects.count() == 5
    assert PhaseWinner.objects.filter(phase=PHASE_1).exists()
    # Distinct points → an unambiguous ranking (not everyone tied at 0).
    assert RankingEntry.objects.filter(total_points__gt=0).count() >= 4


def test_seed_demo_is_idempotent(seeded):
    before = (
        User.objects.count(),
        Prediction.objects.count(),
        Match.objects.filter(phase=PHASE_1, is_scored=True).count(),
    )
    call_command("seed_demo")
    after = (
        User.objects.count(),
        Prediction.objects.count(),
        Match.objects.filter(phase=PHASE_1, is_scored=True).count(),
    )
    assert before == after


@override_settings(DEMO_MODE=True)
def test_demo_login_authenticates_in_demo_mode(client, seeded):
    username = User.objects.order_by("id").first().username
    resp = client.get(reverse("pool:demo_login", args=[username]))
    assert resp.status_code == 302
    assert resp.url == reverse("pool:matches")
    assert client.session.get("_auth_user_id")


def test_demo_login_is_404_when_demo_off(client, seeded):
    # DEMO_MODE defaults to False in the test settings.
    username = User.objects.order_by("id").first().username
    resp = client.get(reverse("pool:demo_login", args=[username]))
    assert resp.status_code == 404


@override_settings(DEMO_MODE=True)
def test_save_prediction_blocked_in_demo(auth_client, make_match):
    match = make_match(phase=PHASE_2)
    resp = auth_client.post(
        reverse("pool:save_prediction"),
        data=json.dumps({"match_id": match.id, "home_goals": 1, "away_goals": 0}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert Prediction.objects.count() == 0
