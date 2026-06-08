"""Template filters for the pool app."""

from django import template

from pool.services.phases import phase_label as _phase_label

register = template.Library()


@register.filter
def phase_label(phase_str):
    """pt-BR phase label, e.g. "Fase de Grupos · 1ª Rodada" / "Oitavas de Final"."""
    return _phase_label(phase_str)
