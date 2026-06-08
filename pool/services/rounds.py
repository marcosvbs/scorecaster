"""Round semantics (spec sections 3, 4 and 7).

A round is the set of matches sharing the same "round" string (FIFA
matchday). It may span several days and closes when its last match is
scored. The current round is the one accepting predictions.
"""

import logging
import re

from pool.models import Match

logger = logging.getLogger(__name__)

# Ordered substring matchers: round string -> Match.phase value.
_PHASE_MATCHERS = [
    ("group", "group"),
    ("round of 32", "round_of_32"),
    ("round of 16", "round_of_16"),
    ("quarter", "quarter_final"),
    ("semi", "semi_final"),
    ("3rd place", "third_place"),
    ("third place", "third_place"),
    ("final", "final"),
]


def phase_from_round(round_str):
    """Map a round string to a Match.phase value."""
    lowered = round_str.lower()
    for needle, phase in _PHASE_MATCHERS:
        if needle in lowered:
            return phase
    logger.warning("Unknown round string %r, falling back to 'group'", round_str)
    return "group"


def round_label(round_str):
    """pt-BR label for a round string, shown to users (cards, history, modal).

    Group rounds get their matchday number ("Fase de Grupos · 1ª Rodada");
    knockout rounds use the phase's pt-BR name ("Oitavas de Final").
    """
    phase = phase_from_round(round_str)
    base = dict(Match.PHASE_CHOICES).get(phase, "Fase de Grupos")
    if phase == "group":
        match = re.search(r"(\d+)", round_str or "")
        if match:
            return f"{base} · {match.group(1)}ª Rodada"
    return base


def get_current_round():
    """Round of the earliest unscored match, or None when nothing is pending.

    Once every match of a round is scored, the earliest unscored match belongs
    to the next round, so the current round advances automatically.
    """
    match = Match.objects.filter(is_scored=False).order_by("starts_at").first()
    return match.round if match else None


def current_round_matches():
    current = get_current_round()
    if current is None:
        return Match.objects.none()
    return Match.objects.filter(round=current)


def future_round_matches():
    """Matches of rounds after the current one (view-only, spec section 4)."""
    current = get_current_round()
    if current is None:
        return Match.objects.none()
    first_start = (
        Match.objects.filter(round=current)
        .order_by("starts_at")
        .values_list("starts_at", flat=True)
        .first()
    )
    return Match.objects.exclude(round=current).filter(starts_at__gt=first_start)


def is_match_in_current_round(match):
    return match.round == get_current_round()
