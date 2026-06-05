"""Thin API-Football v3 client (spec sections 2 and 9).

No DB writes here — management commands persist. Never used in the page
render path. Every failure mode (timeout, HTTP error, bad JSON, API-level
errors) raises ApiFootballError so callers can log and retry later. The API
key is never logged.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class ApiFootballError(Exception):
    pass


class ApiFootballClient:
    def __init__(self, api_key=None, base_url=None, timeout=10):
        self.api_key = api_key or settings.API_FOOTBALL_KEY
        self.base_url = (base_url or settings.API_FOOTBALL_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _get(self, path, params=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = requests.get(
                url,
                params=params or {},
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            # str(exc) never contains the key (it travels in a header).
            raise ApiFootballError(f"Request to {path} failed: {exc}") from exc
        except ValueError as exc:
            raise ApiFootballError(f"Invalid JSON from {path}") from exc

        errors = payload.get("errors")
        if errors:  # API returns 200 with an errors dict (e.g. rate limit)
            raise ApiFootballError(f"API error on {path}: {errors}")
        if "response" not in payload:
            raise ApiFootballError(f"Malformed payload from {path}")
        return payload["response"]

    def get_teams(self, league=None, season=None):
        return self._get(
            "teams",
            {
                "league": league or settings.API_FOOTBALL_LEAGUE_ID,
                "season": season or settings.API_FOOTBALL_SEASON,
            },
        )

    def get_fixtures(self, league=None, season=None):
        return self._get(
            "fixtures",
            {
                "league": league or settings.API_FOOTBALL_LEAGUE_ID,
                "season": season or settings.API_FOOTBALL_SEASON,
            },
        )

    def get_fixtures_by_date(self, date_str, league=None, season=None):
        """One request returns every fixture of the date (request economy)."""
        return self._get(
            "fixtures",
            {
                "date": date_str,
                "league": league or settings.API_FOOTBALL_LEAGUE_ID,
                "season": season or settings.API_FOOTBALL_SEASON,
            },
        )

    def get_fixture(self, fixture_id):
        response = self._get("fixtures", {"id": fixture_id})
        return response[0] if response else None
