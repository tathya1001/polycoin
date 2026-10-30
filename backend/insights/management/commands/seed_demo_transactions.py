"""Dev-only: fill a fresh test account with fictional transactions to build dashboards on.

Every row goes through `create_transaction`, so demo data is encrypted exactly like real
data. All merchant names are made up, never real companies.
"""

import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from categories.models import Category
from categories.services import get_default_category
from datasources.services import first_source
from insights.engine import add_months
from transactions.models import Transaction
from transactions.services import create_transaction
from vault.services import UserCipher

OPENING_BALANCE = Decimal("50000.00")
MAX_MONTHS = 60
MAX_SCALE = 100  # about 31 everyday rows per month at scale 1, so 12 months at 55 is ~20,000

# Once a month: (day, txn_type, category, merchant, lowest amount, highest amount).
MONTHLY = [
    (1, "credit", "Salary", "Acme Corp Payroll", 85000, 85000),
    (3, "debit", "Rent", "Maple Street Homes", 22000, 22000),
    (8, "debit", "Bills", "Northwind Power", 900, 2600),
    (12, "debit", "Bills", "Skyline Mobile", 399, 399),
    (15, "debit", "Entertainment", "Cinestream", 199, 199),
]

# Everyday debits: (category, merchants, lowest amount, highest amount, times a month at scale 1).
EVERYDAY = [
    ("Food", ["Tastybites Cafe", "Spice Route Kitchen", "Daily Dosa"], 120, 900, 10),
    ("Groceries", ["Greenleaf Grocers", "Freshbasket Mart"], 300, 3500, 6),
    ("Transport", ["Cityride Cabs", "Fuelstop", "Metro Card Topup"], 60, 1500, 8),
    ("Shopping", ["Brightmart", "Threadline Apparel"], 500, 6000, 3),
    ("Entertainment", ["Cinestar Screens", "Gamevault"], 200, 1200, 2),
    ("Health", ["Wellcare Pharmacy", "Sunrise Clinic"], 150, 2500, 1),
    ("Transfer", ["Sent to R. Sample"], 500, 5000, 1),
]


def _amount(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100  # whole paise, never a float


def build_rows(today, months: int, scale: int, rng: random.Random) -> list[dict]:
    """The demo rows, oldest first, ending today. Pure: no database, so it's easy to test."""
    rows = []
    for back in range(months - 1, -1, -1):
        month_start = add_months(today.replace(day=1), -back)
        last_day = min(add_months(month_start, 1) - timedelta(days=1), today)

        for day, txn_type, category, merchant, low, high in MONTHLY:
            when = month_start.replace(day=day)  # every MONTHLY day exists in every month
            if when <= last_day:
                rows.append(
                    {"date": when, "txn_type": txn_type, "category": category,
                     "name": merchant, "amount": _amount(rng, low, high)}
                )  # fmt: skip

        for category, merchants, low, high, per_month in EVERYDAY:
            for _ in range(per_month * scale):
                rows.append(
                    {"date": month_start.replace(day=rng.randint(1, last_day.day)),
                     "txn_type": "debit", "category": category,
                     "name": rng.choice(merchants), "amount": _amount(rng, low, high)}
                )  # fmt: skip

    rows.sort(key=lambda row: row["date"])  # stable, so same-day rows keep a fixed order
    balance = OPENING_BALANCE
    for index, row in enumerate(rows):
        balance += row["amount"] if row["txn_type"] == "credit" else -row["amount"]
        row["balance"] = balance
        # The running number keeps every fingerprint unique, even for two identical spends.
        row["description"] = f"DEMO/{row['name'].upper().replace(' ', '')}/{index:05d}"
    return rows


class Command(BaseCommand):
    help = (
        "DEBUG only: add fictional, encrypted transactions to a test user with none yet, "
        "to build and demo dashboards without a real bank statement."
    )

    def add_arguments(self, parser):
        parser.add_argument("--user", required=True, help="Email of an existing test user.")
        parser.add_argument("--months", type=int, default=12, help="How many months back.")
        parser.add_argument(
            "--scale", type=int, default=1, help="Multiplies the everyday spends per month."
        )
        parser.add_argument("--seed", type=int, help="Random seed, for repeatable data.")

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command only runs with DEBUG on: it writes fake data.")
        if not 1 <= options["months"] <= MAX_MONTHS:
            raise CommandError(f"--months must be from 1 to {MAX_MONTHS}.")
        if not 1 <= options["scale"] <= MAX_SCALE:
            raise CommandError(f"--scale must be from 1 to {MAX_SCALE}.")

        user = get_user_model().objects.filter(email__iexact=options["user"]).first()
        if user is None:
            raise CommandError(f"No user with the email {options['user']!r}.")
        if Transaction.objects.filter(user=user).exists():
            raise CommandError(
                "That user already has transactions. Seed a fresh test user, so demo rows "
                "never mix with real ones."
            )

        rng = random.Random(options["seed"])  # no --seed: different data every run
        rows = build_rows(timezone.localdate(), options["months"], options["scale"], rng)
        # A renamed or deleted seed category falls back to the default ("Others").
        categories = {c.name.lower(): c for c in Category.objects.filter(user=user)}
        fallback = get_default_category(user)
        source = first_source(user)
        cipher = UserCipher(user)  # one DEK load for every row

        with transaction.atomic():  # all or nothing: never a half-seeded account
            for row in rows:
                create_transaction(
                    cipher,
                    user,
                    date=row["date"],
                    txn_type=row["txn_type"],
                    name=row["name"],
                    description=row["description"],
                    amount=row["amount"],
                    balance=row["balance"],
                    category=categories.get(row["category"].lower(), fallback),
                    data_source=source,
                )

        self.stdout.write(self.style.SUCCESS(f"Added {len(rows)} demo transactions."))
