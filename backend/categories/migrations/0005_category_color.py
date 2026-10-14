from django.core.validators import RegexValidator
from django.db import migrations, models

# Frozen copy on purpose: migrations must not change if colors.py later does.
PALETTE = [
    "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300",
    "#6250D6", "#E34948", "#0E9FB5", "#8D6E63", "#84A912", "#5B6B7F",
]  # fmt: skip


def give_existing_categories_a_colour(apps, schema_editor):
    """Each user's categories take the palette in A-Z order; "Others" keeps the neutral grey."""
    Category = apps.get_model("categories", "Category")
    seen_per_user: dict = {}
    for category in Category.objects.filter(is_default=False).order_by("user_id", "name"):
        index = seen_per_user.get(category.user_id, 0)
        seen_per_user[category.user_id] = index + 1
        category.color = PALETTE[index % len(PALETTE)]
        category.save(update_fields=["color"])


class Migration(migrations.Migration):

    dependencies = [("categories", "0004_seed_existing_keywords")]

    operations = [
        migrations.AddField(
            model_name="category",
            name="color",
            field=models.CharField(
                default="#9CA3AF",
                max_length=7,
                validators=[RegexValidator(r"^#[0-9A-F]{6}$", "Use a colour like #2A78D6.")],
            ),
        ),
        migrations.RunPython(give_existing_categories_a_colour, migrations.RunPython.noop),
    ]
