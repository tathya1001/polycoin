import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Duplicates are now found per source, so one statement can sit in two sources."""

    dependencies = [
        ('datasources', '0001_initial'),
        ('transactions', '0007_backfill_late_rows'),
    ]

    operations = [
        migrations.AlterField(
            model_name='transaction',
            name='data_source',
            field=models.ForeignKey(db_index=False, on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='datasources.datasource'),
        ),
        migrations.RemoveConstraint(
            model_name='transaction',
            name='uniq_txn_fingerprint_per_user',
        ),
    ]
