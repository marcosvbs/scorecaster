"""Template filters for the pool app."""

from django import template

from pool.services.rounds import round_label as _round_label

register = template.Library()


@register.filter
def round_label(round_str):
    """pt-BR round label, e.g. "Fase de Grupos · 1ª Rodada" / "Oitavas de Final"."""
    return _round_label(round_str)
