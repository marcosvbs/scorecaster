"""Computed-model admin pages must be read-only (no cascade on manual edit)."""

from django.contrib.admin.sites import AdminSite

from pool.admin import PredictionAdmin, RoundWinnerAdmin
from pool.models import Prediction, RoundWinner


def test_computed_admins_are_read_only():
    site = AdminSite()
    for admin_cls, model in ((PredictionAdmin, Prediction), (RoundWinnerAdmin, RoundWinner)):
        admin = admin_cls(model, site)
        assert admin.has_add_permission(None) is False
        assert admin.has_change_permission(None) is False
        assert admin.has_delete_permission(None) is False
