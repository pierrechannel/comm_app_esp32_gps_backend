from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gps", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="gpslocation",
            name="heart_rate",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="gpslocation",
            name="pulse_ok",
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="gpslocation",
            name="pulse_raw",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
