from django.db import migrations


def rebuild_snapshot(apps, schema_editor):
    """Recompute the ranking snapshot so existing rows pick up the phase_*
    columns added in 0006 (which otherwise sit at their defaults until the
    next scored match rebuilds the snapshot)."""
    from pool.services.ranking import rebuild_ranking_snapshot

    rebuild_ranking_snapshot()


class Migration(migrations.Migration):

    dependencies = [
        ("pool", "0006_rankingentry_phase_rankingentry_phase_exact_count_and_more"),
    ]

    operations = [
        migrations.RunPython(rebuild_snapshot, migrations.RunPython.noop),
    ]
