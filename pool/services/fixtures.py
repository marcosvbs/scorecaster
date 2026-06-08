"""Persistence for normalized FIFA matches (seed + result updates).

Kept separate from `fifa_api` (which never touches the DB): this is where a
validated match dict becomes Team/Match rows. Shared by the `seed_world_cup`
and `check_results` commands so team resolution stays identical in both.
"""

from pool.models import Match, Team


def upsert_team(team):
    """Get-or-create the Team a match side points at.

    Real team -> upsert by external_id. Knockout placeholder (team not yet
    known) -> get-or-create a name-keyed row with no external_id, which the
    updater later replaces with the real team once the bracket resolves.
    """
    if team["is_placeholder"]:
        obj, _ = Team.objects.get_or_create(
            name=team["name"], external_id=None, defaults={"flag": ""}
        )
        return obj
    obj, _ = Team.objects.update_or_create(
        external_id=team["external_id"],
        defaults={"name": team["name"], "flag": team["flag"]},
    )
    return obj


def seed_match(match):
    """Upsert a match's schedule + teams (never its score). Used at seed time."""
    return Match.objects.update_or_create(
        external_id=match["external_id"],
        defaults={
            "home_team": upsert_team(match["home"]),
            "away_team": upsert_team(match["away"]),
            "starts_at": match["starts_at"],
            "phase": match["phase"],
            "stage": match["stage"],
            "api_status": match["status"],
        },
    )[0]
