"""Thin api.fifa.com v3 client + normalizers (data source for the pool).

The official fifa.com pages carry no data in HTML; they fetch everything at
runtime from this undocumented public endpoint (no API key). We call it
directly. One `calendar/matches` request returns the full tournament — all
teams, every group match, and the knockout bracket with placeholder slots.

Security: api.fifa.com is undocumented and untrusted. The `normalize_*`
helpers are the trust boundary — every field is validated/coerced here before
it can reach the DB. No DB writes in this module; it is never called in a
request path; raw responses are never logged.
"""

import logging

import requests
from django.conf import settings
from django.utils.dateparse import parse_datetime

from pool.services.rounds import phase_from_round

logger = logging.getLogger(__name__)

# Reject a hostile/garbage multi-MB body before parsing (Railway memory guard).
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# Sanity clamp; a real score never approaches this. Out-of-range -> rejected.
MAX_GOALS = 99
# One page is far larger than the 104-match tournament, so a single request
# returns everything. The loop guard below only matters for a hostile feed.
PAGE_COUNT = 500

# MatchStatus integer enum (reverse-engineered: 0 = finished/played,
# 1 = not started). Overridable via settings once live codes are confirmed.
FINISHED_MATCH_STATUSES = frozenset(getattr(settings, "FIFA_FINISHED_STATUSES", (0,)))

# FIFA StageName -> True when each match of that stage is its own round set.
# Group matches get a synthetic "Group Stage - N" round (per-group matchday).
_GROUP_STAGE_NAME = "First Stage"

# FIFA 3-letter country code -> ISO-2 used by Team.flag_emoji.
FIFA_TO_ISO2 = {
    "ALG": "DZ", "ARG": "AR", "AUS": "AU", "AUT": "AT", "BEL": "BE",
    "BOL": "BO", "BRA": "BR", "CAN": "CA", "CHI": "CL", "COL": "CO",
    "CRC": "CR", "CRO": "HR", "CUW": "CW", "CIV": "CI", "DEN": "DK",
    "ECU": "EC", "EGY": "EG", "ENG": "GB", "ESP": "ES", "FRA": "FR",
    "GER": "DE", "GHA": "GH", "GRE": "GR", "HAI": "HT", "HON": "HN",
    "IRN": "IR", "IRQ": "IQ", "ITA": "IT", "JAM": "JM", "JPN": "JP",
    "JOR": "JO", "KOR": "KR", "KSA": "SA", "MAR": "MA", "MEX": "MX",
    "NED": "NL", "NZL": "NZ", "NGA": "NG", "NOR": "NO", "PAN": "PA",
    "PAR": "PY", "PER": "PE", "POL": "PL", "POR": "PT", "QAT": "QA",
    "RSA": "ZA", "SCO": "GB", "SEN": "SN", "SRB": "RS", "SUI": "CH",
    "SWE": "SE", "TUN": "TN", "TUR": "TR", "UKR": "UA", "URU": "UY",
    "USA": "US", "UZB": "UZ", "VEN": "VE", "WAL": "GB", "CMR": "CM",
    "CPV": "CV", "CZE": "CZ", "BIH": "BA", "COD": "CD",
}

# FIFA 3-letter country code -> Brazilian Portuguese team name (UI display).
# The FIFA feed only carries English names; the audience is Brazilian. Unmapped
# codes fall back to the English name (with a warning) so seeding never breaks.
FIFA_PTBR_NAME = {
    "ALG": "Argélia", "ARG": "Argentina", "AUS": "Austrália", "AUT": "Áustria",
    "BEL": "Bélgica", "BIH": "Bósnia e Herzegovina", "BRA": "Brasil",
    "CAN": "Canadá", "CIV": "Costa do Marfim",
    "COD": "República Democrática do Congo", "COL": "Colômbia",
    "CPV": "Cabo Verde", "CRO": "Croácia", "CUW": "Curaçao", "CZE": "Tchéquia",
    "ECU": "Equador", "EGY": "Egito", "ENG": "Inglaterra", "ESP": "Espanha",
    "FRA": "França", "GER": "Alemanha", "GHA": "Gana", "HAI": "Haiti",
    "IRN": "Irã", "IRQ": "Iraque", "JOR": "Jordânia", "JPN": "Japão",
    "KOR": "Coreia do Sul", "KSA": "Arábia Saudita", "MAR": "Marrocos",
    "MEX": "México", "NED": "Países Baixos", "NOR": "Noruega",
    "NZL": "Nova Zelândia", "PAN": "Panamá", "PAR": "Paraguai",
    "POR": "Portugal", "QAT": "Catar", "RSA": "África do Sul", "SCO": "Escócia",
    "SEN": "Senegal", "SUI": "Suíça", "SWE": "Suécia", "TUN": "Tunísia",
    "TUR": "Turquia", "URU": "Uruguai", "USA": "Estados Unidos",
    "UZB": "Uzbequistão",
}


class FifaApiError(Exception):
    pass


# --- normalizers (trust boundary) -------------------------------------------

def _desc(value):
    """FIFA localized fields are [{Locale, Description}, ...]; take the text."""
    if isinstance(value, list):
        return value[0].get("Description") if value else None
    return value


def _clean_str(value, max_len):
    """Coerce to a stripped, control-char-free, length-bounded string."""
    if value is None:
        return ""
    text = "".join(ch for ch in str(value) if ch == " " or ch.isprintable())
    return text.strip()[:max_len]


def normalize_flag(id_country):
    """3-letter FIFA country code -> validated ISO-2, or '' (renders no flag)."""
    code = _clean_str(id_country, 3).upper()
    iso2 = FIFA_TO_ISO2.get(code, "")
    if len(iso2) == 2 and iso2.isascii() and iso2.isalpha():
        return iso2
    if code:
        logger.warning("No ISO-2 mapping for FIFA country code %r", code)
    return ""


def normalize_score(value):
    """Coerce a score to a bounded non-negative int, or None if absent/invalid."""
    if value is None:
        return None
    try:
        goals = int(value)
    except (TypeError, ValueError):
        logger.warning("Non-integer score %r rejected", value)
        return None
    if goals < 0 or goals > MAX_GOALS:
        logger.warning("Out-of-range score %r rejected", value)
        return None
    return goals


def is_finished(match_status):
    try:
        return int(match_status) in FINISHED_MATCH_STATUSES
    except (TypeError, ValueError):
        return False


def _team_name(id_country, english_name):
    """pt-BR team name from the country code, falling back to the feed's name."""
    code = _clean_str(id_country, 3).upper()
    name = FIFA_PTBR_NAME.get(code)
    if name:
        return name
    if code:
        logger.warning("No pt-BR name for FIFA country code %r, using feed name", code)
    return _clean_str(english_name, 50) or "?"


def _team(side, placeholder):
    """Normalize one match side to a team dict.

    Real team when `IdTeam` is present; otherwise a placeholder (knockout slot
    whose team is not yet known), labelled from `PlaceHolderA/B`.
    """
    if side and side.get("IdTeam") not in (None, ""):
        try:
            external_id = int(side["IdTeam"])
        except (TypeError, ValueError):
            external_id = None
        if external_id is not None:
            return {
                "external_id": external_id,
                "name": _team_name(side.get("IdCountry"), _desc(side.get("TeamName"))),
                "flag": normalize_flag(side.get("IdCountry")),
                "is_placeholder": False,
            }
    label = _clean_str(placeholder, 50) or "A definir"
    return {"external_id": None, "name": label, "flag": "", "is_placeholder": True}


def _group_rounds(raw_matches):
    """Map IdMatch -> 'Group Stage - N' (the pool round = a FIFA matchday).

    FIFA omits a matchday number, but group matches are numbered globally by
    MatchNumber in matchday order (matchday 1 first, etc.). The group stage
    splits evenly into 3 matchdays, so ranking the group matches by MatchNumber
    and cutting into thirds reproduces the matchday — the same grouping
    API-Football labelled "Group Stage - N". This is matchday-wide across all
    groups, not per group.
    """
    group_matches = [
        raw for raw in raw_matches if _desc(raw.get("StageName")) == _GROUP_STAGE_NAME
    ]
    ordered = sorted(
        group_matches, key=lambda m: (m.get("MatchNumber") or 0, m.get("Date") or "")
    )
    total = len(ordered)
    per_matchday = max(1, total // 3)  # 24 for the 48-team / 12-group format

    rounds = {}
    for index, raw in enumerate(ordered):
        matchday = min(3, index // per_matchday + 1)
        rounds[raw.get("IdMatch")] = f"Group Stage - {matchday}"
    return rounds


def normalize_match(raw, group_rounds):
    """Validate one raw FIFA match into a flat dict, or None to skip it."""
    id_match = raw.get("IdMatch")
    if id_match in (None, ""):
        logger.warning("Match without IdMatch skipped")
        return None
    try:
        external_id = int(id_match)
    except (TypeError, ValueError):
        logger.warning("Non-integer IdMatch %r skipped", id_match)
        return None

    starts_at = parse_datetime(_clean_str(raw.get("Date"), 40))
    if starts_at is None:
        logger.warning("Match %s has unparseable Date %r, skipped", external_id, raw.get("Date"))
        return None

    stage_name = _clean_str(_desc(raw.get("StageName")), 50)
    round_str = group_rounds.get(id_match) or stage_name or "Group Stage - 1"

    status = raw.get("MatchStatus")
    return {
        "external_id": external_id,
        "round": round_str[:50],
        "phase": phase_from_round(round_str),
        "starts_at": starts_at,
        "status": _clean_str(status, 10),
        "is_finished": is_finished(status),
        "home": _team(raw.get("Home"), raw.get("PlaceHolderA")),
        "away": _team(raw.get("Away"), raw.get("PlaceHolderB")),
        "home_goals": normalize_score(raw.get("HomeTeamScore")),
        "away_goals": normalize_score(raw.get("AwayTeamScore")),
    }


def normalize_matches(raw_matches):
    """Normalize the full match list, dropping any malformed entries."""
    group_rounds = _group_rounds(raw_matches)
    normalized = [normalize_match(raw, group_rounds) for raw in raw_matches]
    return [match for match in normalized if match is not None]


# --- client -----------------------------------------------------------------

class FifaApiClient:
    def __init__(self, base_url=None, competition_id=None, season_id=None, timeout=10):
        self.base_url = (base_url or settings.FIFA_API_BASE_URL).rstrip("/")
        self.competition_id = competition_id or settings.FIFA_COMPETITION_ID
        self.season_id = season_id or settings.FIFA_SEASON_ID
        self.timeout = timeout

    def _get(self, path, params=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = requests.get(
                url,
                params=params or {},
                headers={
                    "User-Agent": "world-cup-26-pool/1.0",
                    "Accept": "application/json",
                },
                timeout=self.timeout,
                allow_redirects=False,  # never follow a redirect off the FIFA host
            )
            if response.is_redirect or response.is_permanent_redirect:
                raise FifaApiError(
                    f"Unexpected redirect from {path} to "
                    f"{response.headers.get('Location')!r}"
                )
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                raise FifaApiError(f"Non-JSON response from {path}: {content_type!r}")
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise FifaApiError(
                    f"Response from {path} too large: {len(response.content)} bytes"
                )
            payload = response.json()
        except requests.RequestException as exc:
            raise FifaApiError(f"Request to {path} failed: {exc}") from exc
        except ValueError as exc:
            raise FifaApiError(f"Invalid JSON from {path}") from exc

        if not isinstance(payload, dict):
            raise FifaApiError(f"Malformed payload from {path}")
        return payload

    def get_all_matches(self):
        """Return the raw `Results` list for the configured competition/season."""
        payload = self._get(
            "calendar/matches",
            {
                "idCompetition": self.competition_id,
                "idSeason": self.season_id,
                "count": PAGE_COUNT,
                "language": "en",
            },
        )
        results = payload.get("Results")
        if not isinstance(results, list):
            raise FifaApiError("calendar/matches returned no Results list")
        if len(results) >= PAGE_COUNT and payload.get("ContinuationToken"):
            # Tournament is 104 matches, far under PAGE_COUNT; if this ever
            # trips, the feed grew and pagination must be added.
            logger.warning("calendar/matches may be truncated at %d results", len(results))
        return results
