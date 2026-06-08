from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from pool.models import Team, Match

# Fixed mid-day instant (12:00 in America/Sao_Paulo) shared by view tests.
FROZEN_NOW = datetime(2026, 6, 15, 15, 0, tzinfo=dt_timezone.utc)


@pytest.fixture(autouse=True)
def clear_cache():
    """LocMem cache outlives transactions; reset throttle counters per test."""
    cache.clear()
    yield


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: FROZEN_NOW)
    return FROZEN_NOW


@pytest.fixture
def client(db):
    return Client()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="rafael", password="test123")


@pytest.fixture
def auth_client(client, user):
    client.login(username="rafael", password="test123")
    return client


@pytest.fixture
def teams(db):
    home = Team.objects.create(name="Brasil", flag="BR")
    away = Team.objects.create(name="Argentina", flag="AR")
    return home, away


@pytest.fixture
def make_match(teams):
    home, away = teams

    def _make(starts_at=None, phase="group", round="", **kwargs):
        return Match.objects.create(
            home_team=home,
            away_team=away,
            phase=phase,
            round=round,
            starts_at=starts_at or timezone.now() + timezone.timedelta(hours=2),
            **kwargs,
        )

    return _make
