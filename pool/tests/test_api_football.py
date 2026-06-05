from unittest import mock

import pytest
import requests

from pool.services.api_football import ApiFootballClient, ApiFootballError


@pytest.fixture
def api_client(settings):
    settings.API_FOOTBALL_KEY = "test-key"
    settings.API_FOOTBALL_BASE_URL = "https://api.test"
    return ApiFootballClient()


def fake_response(json_data=None, status=200, raise_json=False):
    resp = mock.Mock()
    resp.status_code = status
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
    else:
        resp.raise_for_status.return_value = None
    if raise_json:
        resp.json.side_effect = ValueError("bad json")
    else:
        resp.json.return_value = json_data
    return resp


@mock.patch("pool.services.api_football.requests.get")
def test_get_fixtures_success(mock_get, api_client):
    mock_get.return_value = fake_response({"errors": [], "response": [{"fixture": 1}]})

    result = api_client.get_fixtures(league=1, season=2026)

    assert result == [{"fixture": 1}]
    args, kwargs = mock_get.call_args
    assert args[0] == "https://api.test/fixtures"
    assert kwargs["headers"] == {"x-apisports-key": "test-key"}
    assert kwargs["params"] == {"league": 1, "season": 2026}


@mock.patch("pool.services.api_football.requests.get")
def test_get_fixtures_by_date_sends_date_param(mock_get, api_client):
    mock_get.return_value = fake_response({"errors": [], "response": []})

    api_client.get_fixtures_by_date("2026-06-15", league=1, season=2026)

    assert mock_get.call_args.kwargs["params"]["date"] == "2026-06-15"


@mock.patch("pool.services.api_football.requests.get")
def test_http_error_raises(mock_get, api_client):
    mock_get.return_value = fake_response(status=500)

    with pytest.raises(ApiFootballError):
        api_client.get_teams()


@mock.patch("pool.services.api_football.requests.get")
def test_timeout_raises(mock_get, api_client):
    mock_get.side_effect = requests.Timeout("timed out")

    with pytest.raises(ApiFootballError):
        api_client.get_fixtures()


@mock.patch("pool.services.api_football.requests.get")
def test_invalid_json_raises(mock_get, api_client):
    mock_get.return_value = fake_response(raise_json=True)

    with pytest.raises(ApiFootballError):
        api_client.get_fixtures()


@mock.patch("pool.services.api_football.requests.get")
def test_api_level_errors_raise(mock_get, api_client):
    # API-Football returns 200 with an errors dict (e.g. rate limit hit).
    mock_get.return_value = fake_response(
        {"errors": {"requests": "limit reached"}, "response": []}
    )

    with pytest.raises(ApiFootballError):
        api_client.get_fixtures()


@mock.patch("pool.services.api_football.requests.get")
def test_malformed_payload_raises(mock_get, api_client):
    mock_get.return_value = fake_response({"unexpected": True})

    with pytest.raises(ApiFootballError):
        api_client.get_fixtures()


@mock.patch("pool.services.api_football.requests.get")
def test_get_fixture_returns_first_or_none(mock_get, api_client):
    mock_get.return_value = fake_response({"errors": [], "response": [{"id": 7}]})
    assert api_client.get_fixture(7) == {"id": 7}

    mock_get.return_value = fake_response({"errors": [], "response": []})
    assert api_client.get_fixture(8) is None


@mock.patch("pool.services.api_football.requests.get")
def test_error_message_never_contains_key(mock_get, api_client):
    mock_get.return_value = fake_response(status=403)

    with pytest.raises(ApiFootballError) as excinfo:
        api_client.get_teams()

    assert "test-key" not in str(excinfo.value)
