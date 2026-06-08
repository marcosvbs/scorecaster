from unittest import mock

import pytest
import requests

from pool.services.fifa_api import (
    FifaApiClient,
    FifaApiError,
    is_finished,
    normalize_flag,
    normalize_matches,
    normalize_score,
)
from pool.tests.fifa_factories import fifa_match


@pytest.fixture
def api_client(settings):
    settings.FIFA_API_BASE_URL = "https://api.test"
    settings.FIFA_COMPETITION_ID = "17"
    settings.FIFA_SEASON_ID = "285023"
    return FifaApiClient()


def fake_response(json_data=None, status=200, content_type="application/json",
                  raise_json=False, content=b"{}", is_redirect=False):
    resp = mock.Mock()
    resp.status_code = status
    resp.is_redirect = is_redirect
    resp.is_permanent_redirect = False
    resp.headers = {"Content-Type": content_type, "Location": "https://evil.test"}
    resp.content = content
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    if raise_json:
        resp.json.side_effect = ValueError("bad json")
    else:
        resp.json.return_value = json_data
    return resp


# --- client transport -------------------------------------------------------

@mock.patch("pool.services.fifa_api.requests.get")
def test_get_all_matches_success(mock_get, api_client):
    mock_get.return_value = fake_response({"Results": [fifa_match(100)]})

    results = api_client.get_all_matches()

    assert len(results) == 1 and results[0]["IdMatch"] == 100
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.test/calendar/matches"
    assert kwargs["params"]["idCompetition"] == "17"
    assert kwargs["allow_redirects"] is False  # never follow a hostile redirect


@mock.patch("pool.services.fifa_api.requests.get")
def test_http_error_raises_fifa_error(mock_get, api_client):
    mock_get.return_value = fake_response(status=503)
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


@mock.patch("pool.services.fifa_api.requests.get")
def test_non_json_content_type_rejected(mock_get, api_client):
    mock_get.return_value = fake_response(content_type="text/html")
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


@mock.patch("pool.services.fifa_api.requests.get")
def test_invalid_json_raises_fifa_error(mock_get, api_client):
    mock_get.return_value = fake_response(raise_json=True)
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


@mock.patch("pool.services.fifa_api.requests.get")
def test_oversized_response_rejected(mock_get, api_client):
    mock_get.return_value = fake_response(
        {"Results": []}, content=b"x" * (8 * 1024 * 1024 + 1)
    )
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


@mock.patch("pool.services.fifa_api.requests.get")
def test_redirect_rejected(mock_get, api_client):
    mock_get.return_value = fake_response(is_redirect=True)
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


@mock.patch("pool.services.fifa_api.requests.get")
def test_missing_results_list_raises(mock_get, api_client):
    mock_get.return_value = fake_response({"ContinuationToken": "x"})
    with pytest.raises(FifaApiError):
        api_client.get_all_matches()


# --- normalizers ------------------------------------------------------------

def test_normalize_flag_maps_known_country():
    assert normalize_flag("BRA") == "BR"


def test_normalize_flag_unknown_is_empty():
    assert normalize_flag("XYZ") == ""
    assert normalize_flag(None) == ""


def test_normalize_score_bounds_and_types():
    assert normalize_score(3) == 3
    assert normalize_score(None) is None
    assert normalize_score(-1) is None       # negative rejected
    assert normalize_score(1000) is None      # absurd rejected
    assert normalize_score("nan") is None     # non-int rejected


def test_is_finished_decodes_status():
    assert is_finished(0) is True
    assert is_finished(1) is False
    assert is_finished(None) is False
    assert is_finished("x") is False


def test_normalize_match_full_fields():
    [m] = normalize_matches([fifa_match(100, home_score=2, away_score=1)])
    assert m["external_id"] == 100
    assert m["phase"] == "Group Stage - 1"
    assert m["stage"] == "group"
    assert m["is_finished"] is True
    assert m["home"]["external_id"] == 10
    assert m["home"]["flag"] == "BR"
    assert (m["home_goals"], m["away_goals"]) == (2, 1)


def test_normalize_knockout_placeholder_side():
    raw = fifa_match(
        200, stage="Round of 32", group=None, home_id=None, away_id=None,
        placeholder_a="1A", placeholder_b="2B",
    )
    [m] = normalize_matches([raw])
    assert m["home"]["is_placeholder"] is True
    assert m["home"]["name"] == "1A"
    assert m["home"]["external_id"] is None


# --- security: untrusted feed cannot corrupt the DB or escape templates -----

def test_malicious_team_name_is_length_bounded_and_clean():
    # Unmapped country -> name falls back to the (untrusted) feed name, which is
    # the path that must be sanitized. Bounded to the model max_length; Django
    # autoescape (no |safe in templates) neutralizes the markup on render.
    raw = fifa_match(
        100, home_country="XYZ", home="<script>alert(1)</script>" + "A" * 200
    )
    [m] = normalize_matches([raw])
    assert len(m["home"]["name"]) <= 50


def test_bad_country_code_does_not_break_flag():
    raw = fifa_match(100, home_country="'; DROP TABLE--")
    [m] = normalize_matches([raw])
    assert m["home"]["flag"] == ""  # never fed unvalidated into flag_svg


def test_out_of_range_score_is_dropped_not_stored():
    raw = fifa_match(100, home_score=99999, away_score=1)
    [m] = normalize_matches([raw])
    assert m["home_goals"] is None  # absurd score rejected, not persisted


def test_unparseable_date_match_is_skipped():
    bad = fifa_match(100, date="not-a-date")
    good = fifa_match(101)
    out = normalize_matches([bad, good])
    assert [m["external_id"] for m in out] == [101]


def test_non_integer_id_match_is_skipped():
    out = normalize_matches([fifa_match("abc"), fifa_match(101)])
    assert [m["external_id"] for m in out] == [101]
