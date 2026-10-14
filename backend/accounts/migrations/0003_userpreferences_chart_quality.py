from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("accounts", "0002_userpreferences")]

    operations = [
        migrations.AddField(
            model_name="userpreferences",
            name="chart_quality",
            field=models.CharField(
                choices=[("quality", "High quality"), ("performance", "Performance")],
                default="quality",
                max_length=16,
            ),
        ),
    ]
