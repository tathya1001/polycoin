from django.db import migrations

# Frozen copy on purpose: migrations must not change if services.py later does.
SEED = [
    "Others", "Food", "Groceries", "Transport", "Shopping", "Bills",
    "Rent", "Salary", "Transfer", "Entertainment", "Health",
]


def seed(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Category = apps.get_model("categories", "Category")
    Category.objects.bulk_create(
        [
            Category(user_id=user_id, name=name, is_default=(name == "Others"))
            for user_id in User.objects.values_list("id", flat=True)
            for name in SEED
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("categories", "0001_initial"),
    ]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
