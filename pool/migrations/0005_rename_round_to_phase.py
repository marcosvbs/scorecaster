from django.db import migrations


class Migration(migrations.Migration):
    """Rename the "round" terminology to "phase" (data-preserving renames).

    - Match: the broad stage-code field `phase` -> `stage`; the granular
      phase-string field `round` -> `phase`. Renamed in this order so `phase`
      is free before `round` takes it.
    - RoundWinner -> PhaseWinner, its `round` field -> `phase` (RenameField
      also updates the unique_together reference).

    No row values change; the stage codes (group/round_of_16/…) are untouched.
    """

    dependencies = [
        ("pool", "0004_rankingentry"),
    ]

    operations = [
        migrations.RenameField(
            model_name="match",
            old_name="phase",
            new_name="stage",
        ),
        migrations.RenameField(
            model_name="match",
            old_name="round",
            new_name="phase",
        ),
        migrations.RenameModel(
            old_name="RoundWinner",
            new_name="PhaseWinner",
        ),
        migrations.RenameField(
            model_name="phasewinner",
            old_name="round",
            new_name="phase",
        ),
    ]
