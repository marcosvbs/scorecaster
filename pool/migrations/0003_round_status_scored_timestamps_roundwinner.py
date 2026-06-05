import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def mark_finished_matches_scored(apps, schema_editor):
    """Matches that already have a final score were scored under the old flow."""
    Match = apps.get_model("pool", "Match")
    Match.objects.filter(
        home_goals__isnull=False, away_goals__isnull=False
    ).update(is_scored=True)


class Migration(migrations.Migration):

    dependencies = [
        ("pool", "0002_external_id_and_round_of_32"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="match",
            name="round",
            field=models.CharField(blank=True, default="", max_length=50),
        ),
        migrations.AddField(
            model_name="match",
            name="api_status",
            field=models.CharField(blank=True, default="NS", max_length=10),
        ),
        migrations.AddField(
            model_name="match",
            name="is_scored",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="prediction",
            name="created_at",
            field=models.DateTimeField(
                auto_now_add=True, default=django.utils.timezone.now
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="prediction",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.CreateModel(
            name="RoundWinner",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("round", models.CharField(max_length=50)),
                ("points", models.IntegerField()),
                ("exact_count", models.IntegerField(default=0)),
                ("partial_count", models.IntegerField(default=0)),
                ("computed_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "unique_together": {("round", "user")},
            },
        ),
        migrations.RunPython(
            mark_finished_matches_scored, migrations.RunPython.noop
        ),
    ]
