import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Adds only. The code still serving keeps working, so the old unique constraint stays."""

    dependencies = [
        ('datasources', '0001_initial'),
        ('transactions', '0004_transaction_notes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='data_source',
            field=models.ForeignKey(db_index=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='transactions', to='datasources.datasource'),
        ),
        migrations.AddConstraint(
            model_name='transaction',
            constraint=models.UniqueConstraint(fields=('data_source', 'fingerprint'), name='uniq_txn_fingerprint_per_source'),
        ),
        migrations.AddIndex(
            model_name='transaction',
            index=models.Index(fields=['data_source', 'date'], name='txn_source_date_idx'),
        ),
        migrations.CreateModel(
            name='TransferLink',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('credit', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='credit_link', to='transactions.transaction')),
                ('debit', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='debit_link', to='transactions.transaction')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [
                    models.CheckConstraint(condition=models.Q(('debit', models.F('credit')), _negated=True), name='link_joins_two_transactions'),
                ],
            },
        ),
    ]
