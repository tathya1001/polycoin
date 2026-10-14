from django.db import migrations

# Frozen copy on purpose: migrations must not change if services.py later does.
KEYWORDS = {
    "food": ["restaurant", "food delivery", "cafe", "dining", "takeaway", "lunch"],
    "groceries": ["supermarket", "grocery", "vegetables", "fruits", "provisions", "milk"],
    "transport": ["taxi", "cab", "metro", "bus", "train", "fuel", "petrol", "parking"],
    "shopping": ["online shopping", "clothes", "electronics", "footwear", "mall"],
    "bills": ["electricity", "water", "mobile recharge", "internet", "gas", "utility bill"],
    "rent": ["house rent", "rent payment", "landlord"],
    "salary": ["salary credit", "payroll", "income"],
    "transfer": ["bank transfer", "money transfer", "sent to friend", "self transfer"],
    "entertainment": ["movies", "streaming", "music", "concert", "games"],
    "health": ["hospital", "pharmacy", "doctor", "medicine", "insurance"],
}


def seed(apps, schema_editor):
    """Give users who registered before this table existed the same starter vocabulary the
    AI used to read from code, so their proposals don't change on upgrade."""
    Category = apps.get_model("categories", "Category")
    CategoryKeyword = apps.get_model("categories", "CategoryKeyword")
    CategoryKeyword.objects.bulk_create(
        [
            CategoryKeyword(category_id=category_id, term=term)
            for category_id, name in Category.objects.values_list("id", "name")
            for term in KEYWORDS.get(name.lower(), [])
        ],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [("categories", "0003_categorykeyword")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
