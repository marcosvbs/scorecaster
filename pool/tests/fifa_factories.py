"""Builders for raw api.fifa.com match payloads used across tests.

Mirrors the real `calendar/matches` Results shape: localized fields are lists
of {Locale, Description}, scores live on the match, teams carry IdTeam /
IdCountry, and knockout slots use PlaceHolderA/B with Home/Away = None.
"""


def _localized(text):
    return [{"Locale": "en-GB", "Description": text}]


def fifa_team(team_id, name, country):
    if team_id is None:
        return None
    return {
        "IdTeam": str(team_id),
        "TeamName": _localized(name),
        "IdCountry": country,
        "Abbreviation": country,
    }


def fifa_match(
    id_match,
    *,
    status=0,
    home_id=10,
    away_id=26,
    home="Brasil",
    away="Argentina",
    home_country="BRA",
    away_country="ARG",
    home_score=2,
    away_score=1,
    home_penalty=None,
    away_penalty=None,
    stage="First Stage",
    group="Group A",
    id_group="G1",
    date="2026-06-11T19:00:00Z",
    match_number=1,
    placeholder_a="A1",
    placeholder_b="A2",
):
    return {
        "IdMatch": id_match,
        "Date": date,
        "StageName": _localized(stage),
        "GroupName": _localized(group) if group else [],
        "IdGroup": id_group,
        "MatchNumber": match_number,
        "Home": fifa_team(home_id, home, home_country),
        "Away": fifa_team(away_id, away, away_country),
        "PlaceHolderA": placeholder_a,
        "PlaceHolderB": placeholder_b,
        "HomeTeamScore": home_score,
        "AwayTeamScore": away_score,
        "HomeTeamPenaltyScore": home_penalty,
        "AwayTeamPenaltyScore": away_penalty,
        "MatchStatus": status,
    }
