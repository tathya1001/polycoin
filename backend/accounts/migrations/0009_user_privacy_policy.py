from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_userpreferences_theme_default_system'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='privacy_policy_accepted_at',
            field=models.DateTimeField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='user',
            name='privacy_policy_version',
            field=models.CharField(default='', editable=False, max_length=20),
        ),
    ]
