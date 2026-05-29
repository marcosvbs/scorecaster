from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pool", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="external_id",
            field=models.IntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AddField(
            model_name="match",
            name="external_id",
            field=models.IntegerField(blank=True, null=True, unique=True),
        ),
        migrations.AlterField(
            model_name="match",
            name="phase",
            field=models.CharField(
                choices=[
                    ("group", "Fase de Grupos"),
                    ("round_of_32", "32-avos de Final"),
                    ("round_of_16", "Oitavas de Final"),
                    ("quarter_final", "Quartas de Final"),
                    ("semi_final", "Semifinal"),
                    ("third_place", "Disputa de Terceiro Lugar"),
                    ("final", "Final"),
                ],
                max_length=20,
            ),
        ),
    ]
