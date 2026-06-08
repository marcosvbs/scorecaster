import re
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone
from pool.models import Team, Match, Prediction

# Freeze "now" to a fixed mid-day instant so +/- hour offsets stay on the same
# local calendar date (the view filters today's matches by local date).
FROZEN_NOW = datetime(2026, 6, 15, 15, 0, tzinfo=dt_timezone.utc)  # 12:00 in America/Sao_Paulo


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: FROZEN_NOW)


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


def make_match(teams, starts_at, stage="group", phase=""):
    home, away = teams
    return Match.objects.create(
        home_team=home, away_team=away, stage=stage, phase=phase, starts_at=starts_at
    )


def find(matches, match_id):
    return next(m for m in matches if m.id == match_id)


def test_requires_login(client):
    resp = client.get("/")
    assert resp.status_code == 302
    assert "/login/" in resp.url


def test_open_match_is_today_and_open(auth_client, teams):
    match = make_match(teams, timezone.now() + timezone.timedelta(hours=2))

    resp = auth_client.get("/")

    today = resp.context["today_matches"]
    assert find(today, match.id).status == "open"


def test_match_with_prediction_is_predicted(auth_client, teams, user):
    match = make_match(teams, timezone.now() + timezone.timedelta(hours=2))
    Prediction.objects.create(user=user, match=match, home_goals=1, away_goals=0)

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).status == "predicted"


def test_cards_show_ptbr_phase_label_and_date(auth_client, teams):
    make_match(teams, timezone.now() + timezone.timedelta(hours=2), phase="Group Stage - 1")
    make_match(teams, timezone.now() + timezone.timedelta(days=5), phase="Group Stage - 2")

    html = auth_client.get("/").content.decode("utf-8")

    assert "Fase de Grupos · 1ª Rodada" in html  # current-phase card
    assert "15/06" in html                       # kickoff date on the card
    assert "Fase de Grupos · 2ª Rodada" in html  # upcoming tab grouper
    assert "Group Stage" not in html             # raw English phase never leaks


def test_match_past_deadline_is_locked(auth_client, teams):
    # Started an hour ago: still today, but the 30-min deadline has passed.
    match = make_match(teams, timezone.now() - timezone.timedelta(hours=1))

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).status == "locked"


def test_scored_match_is_locked_even_before_deadline(auth_client, teams):
    # Future kickoff (deadline not passed) but already scored -> locked.
    match = make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), phase="Group Stage - 1"
    )
    # A pending sibling keeps the phase current, so the scored match stays in
    # the current-phase tab instead of advancing out of it.
    make_match(
        teams, timezone.now() + timezone.timedelta(days=2), phase="Group Stage - 1"
    )
    match.home_goals = 1
    match.away_goals = 0
    match.save()  # scores the match

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).status == "locked"


def test_future_phases_separated_from_current(auth_client, teams):
    current_match = make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), phase="Group Stage - 1"
    )
    future_match = make_match(
        teams, timezone.now() + timezone.timedelta(days=3), phase="Group Stage - 2"
    )

    resp = auth_client.get("/")

    current_ids = {m.id for m in resp.context["today_matches"]}
    upcoming_ids = {m.id for m in resp.context["upcoming_matches"]}
    assert current_match.id in current_ids
    assert future_match.id in upcoming_ids
    assert current_match.id not in upcoming_ids


def test_multi_day_phase_fully_in_current_tab(auth_client, teams):
    """A phase spans several days; all its matches belong to the current tab."""
    early = make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), phase="Group Stage - 1"
    )
    late = make_match(
        teams, timezone.now() + timezone.timedelta(days=2), phase="Group Stage - 1"
    )

    resp = auth_client.get("/")

    current_ids = {m.id for m in resp.context["today_matches"]}
    assert {early.id, late.id} <= current_ids
    assert len(resp.context["upcoming_matches"]) == 0


def test_knockout_phase_flag(auth_client, teams):
    match = make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), stage="round_of_32"
    )

    resp = auth_client.get("/")

    assert find(resp.context["today_matches"], match.id).is_knockout is True


def test_tab_labels_renamed(auth_client, teams):
    make_match(teams, timezone.now() + timezone.timedelta(hours=2))

    resp = auth_client.get("/")
    html = resp.content.decode()

    assert "Fase atual" in html
    assert "Próximos jogos" in html
    assert ">Hoje<" not in html


def test_tempo_normal_text_removed(auth_client, teams):
    make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), stage="round_of_16"
    )

    resp = auth_client.get("/")

    assert "Palpite vale para o tempo normal" not in resp.content.decode()


def _close_phase(teams, phase_str, starts_at, user):
    match = make_match(teams, starts_at, phase=phase_str)
    Prediction.objects.create(user=user, match=match, home_goals=1, away_goals=0)
    match.home_goals = 1
    match.away_goals = 0
    match.save()
    return match


def test_winner_card_shown_after_phase_closes(auth_client, teams, user):
    _close_phase(
        teams, "Group Stage - 1", timezone.now() - timezone.timedelta(days=1), user
    )
    # next phase exists but has not started yet
    make_match(
        teams, timezone.now() + timezone.timedelta(days=1), phase="Group Stage - 2"
    )

    resp = auth_client.get("/")

    winner = resp.context["phase_winner"]
    assert winner is not None
    assert winner.user.username == "rafael"
    assert winner.points == 10


def test_winner_card_hidden_once_next_phase_starts(auth_client, teams, user):
    _close_phase(
        teams, "Group Stage - 1", timezone.now() - timezone.timedelta(days=1), user
    )
    # first match of the next phase already kicked off
    make_match(
        teams, timezone.now() - timezone.timedelta(minutes=10), phase="Group Stage - 2"
    )

    resp = auth_client.get("/")

    assert resp.context["phase_winner"] is None


def test_winner_card_hidden_when_no_winner_rows(auth_client, teams, user):
    """Closed phase without predictions produces no PhaseWinner -> no card."""
    match = make_match(
        teams, timezone.now() - timezone.timedelta(days=1), phase="Group Stage - 1"
    )
    match.home_goals = 1
    match.away_goals = 0
    match.save()

    resp = auth_client.get("/")

    assert resp.context["phase_winner"] is None


def test_winner_card_hidden_while_phase_in_progress(auth_client, teams, user):
    make_match(
        teams, timezone.now() + timezone.timedelta(hours=2), phase="Group Stage - 1"
    )

    resp = auth_client.get("/")

    assert resp.context["phase_winner"] is None


def test_winner_card_lists_multiple_winners(auth_client, teams, user):
    other = User.objects.create_user(username="ana", password="x")
    match = make_match(
        teams, timezone.now() - timezone.timedelta(days=1), phase="Group Stage - 1"
    )
    # both miss -> 0 points each -> multiple winners (spec 7.4)
    Prediction.objects.create(user=user, match=match, home_goals=1, away_goals=0)
    Prediction.objects.create(user=other, match=match, home_goals=2, away_goals=0)
    match.home_goals = 0
    match.away_goals = 1
    match.save()

    resp = auth_client.get("/")

    winner = resp.context["phase_winner"]
    assert winner is not None
    assert winner.user.username == "ana, rafael"


def test_team_name_is_js_escaped_in_onclick(auth_client, db):
    """A quote in a team name (API-supplied or admin typo) must not break out
    of the JS string inside onclick — escapejs, not just HTML autoescaping,
    because browsers decode entities before the JS parser runs."""
    payload = "x', alert(1), '"
    home = Team.objects.create(name=payload, flag="XX")
    away = Team.objects.create(name="Argentina", flag="AR")
    Match.objects.create(
        home_team=home,
        away_team=away,
        stage="group",
        starts_at=timezone.now() + timezone.timedelta(hours=2),
    )

    resp = auth_client.get("/")
    html = resp.content.decode()

    # escapejs form inside the onclick JS string
    assert "x\\u0027, alert(1), \\u0027" in html
    # No onclick may carry the entity-encoded quote: the browser decodes
    # entities in attributes BEFORE the JS parser runs, so &#x27; there would
    # still break out. (The visible <span> text keeps &#x27; — safe in HTML.)
    onclick_attrs = re.findall(r'onclick="([^"]*)"', html)
    assert onclick_attrs  # match card rendered
    assert not any("&#x27;" in attr for attr in onclick_attrs)
