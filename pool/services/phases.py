"""Phase semantics (spec sections 3, 4 and 7).

A phase is the set of matches sharing the same `phase` string (FIFA
matchday). It may span several days and closes when its last match is
scored. The current phase is the one accepting predictions.
"""

import logging
import re

from pool.models import Match

logger = logging.getLogger(__name__)

# Ordered substring matchers: phase string -> Match.stage value. The needles
# match FIFA's English StageName text from the feed; the output codes (e.g.
# "round_of_16") intentionally mirror FIFA's own naming.
_STAGE_MATCHERS = [
    ("group", "group"),
    ("round of 32", "round_of_32"),
    ("round of 16", "round_of_16"),
    ("quarter", "quarter_final"),
    ("semi", "semi_final"),
    ("3rd place", "third_place"),
    ("third place", "third_place"),
    ("final", "final"),
]


def stage_from_phase(phase_str):
    """Map a phase string to a Match.stage value."""
    lowered = phase_str.lower()
    for needle, stage in _STAGE_MATCHERS:
        if needle in lowered:
            return stage
    logger.warning("Unknown phase string %r, falling back to 'group'", phase_str)
    return "group"


def phase_label(phase_str):
    """pt-BR label for a phase string, shown to users (cards, history, modal).

    Group phases get their matchday number ("Fase de Grupos · 1ª Rodada");
    knockout phases use the stage's pt-BR name ("Oitavas de Final").
    """
    stage = stage_from_phase(phase_str)
    base = dict(Match.STAGE_CHOICES).get(stage, "Fase de Grupos")
    if stage == "group":
        match = re.search(r"(\d+)", phase_str or "")
        if match:
            return f"{base} · {match.group(1)}ª Rodada"
    return base


def get_current_phase():
    """Phase of the earliest unscored match, or None when nothing is pending.

    Once every match of a phase is scored, the earliest unscored match belongs
    to the next phase, so the current phase advances automatically.
    """
    match = Match.objects.filter(is_scored=False).order_by("starts_at").first()
    return match.phase if match else None


def current_phase_matches():
    current = get_current_phase()
    if current is None:
        return Match.objects.none()
    return Match.objects.filter(phase=current)


def future_phase_matches():
    """Matches of phases after the current one (view-only, spec section 4)."""
    current = get_current_phase()
    if current is None:
        return Match.objects.none()
    first_start = (
        Match.objects.filter(phase=current)
        .order_by("starts_at")
        .values_list("starts_at", flat=True)
        .first()
    )
    return Match.objects.exclude(phase=current).filter(starts_at__gt=first_start)


def is_match_in_current_phase(match):
    return match.phase == get_current_phase()
