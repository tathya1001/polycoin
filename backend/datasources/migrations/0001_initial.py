import django.core.validators
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DataSource',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('name_enc', models.BinaryField(null=True)),
                ('name_index', models.BinaryField(max_length=32, null=True)),
                ('color', models.CharField(default='#2A78D6', max_length=7, validators=[django.core.validators.RegexValidator('^#[0-9A-F]{6}$', 'Use a colour like #2A78D6.')])),
                ('position', models.PositiveSmallIntegerField(default=0)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['position', 'created_at'],
                'constraints': [
                    models.UniqueConstraint(fields=('user', 'name_index'), name='uniq_source_name_per_user'),
                    models.UniqueConstraint(condition=models.Q(('name_index__isnull', True)), fields=('user',), name='one_unnamed_source_per_user'),
                ],
            },
        ),
    ]
