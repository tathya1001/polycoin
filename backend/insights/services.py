"""Where insights touches the database and the vault.

Charts: amounts are encrypted, so SQL can't add them up. Plain columns narrow the rows in
the DB first, then the survivors are decrypted in memory for this one request and handed to
the pure engine. Nothing is stored, cached or logged.

Dashboards: the encrypt / decrypt helpers for names, titles and panel configs, and the
builder for starter templates.
"""

import json
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from transactions.models import Transaction
from vault.services import UserCipher

from . import engine
from .models import Dashboard, Panel
from .spec import MIN_DATE, SpecError, resolve_period, validate_filters, validate_spec
from .templates import TEMPLATES


class TooManyRows(Exception):
    """The period holds more transactions than one request may decrypt."""


def load_rows(
    user,
    start: date,
    end: date,
    types: tuple = (),
    category_ids: tuple = (),
    need: frozenset = frozenset(),
) -> list[dict]:
    """The user's transactions from `start` to `end` as the plain dicts the engine reads.

    `types` and `category_ids` narrow the rows in the DB; empty means "don't filter".
    `amount` is always decrypted (every measure reads it). Pass "name" and/or "balance" in
    `need` only when a panel uses them, so we skip decrypting what nobody looks at.
    """
    queryset = Transaction.objects.filter(user=user, date__range=(start, end))
    if types:
        queryset = queryset.filter(txn_type__in=types)
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)

    # Count BEFORE fetching or decrypting anything, so a huge range costs one cheap query.
    if queryset.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows(
            f"More than {settings.INSIGHTS_MAX_ROWS} transactions in the period."
        )

    cipher = UserCipher(user)  # one DEK load for every row

    def dec(blob, context):
        return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview

    rows = []
    for txn in queryset.select_related("category"):
        rows.append(
            {
                "date": txn.date,
                "txn_type": txn.txn_type,
                "category_id": str(txn.category_id),  # for each panel's own category filter
                "category_name": txn.category.name,
                "amount": Decimal(dec(txn.amount_enc, "txn.amount")),
                "name": dec(txn.name_enc, "txn.name") if "name" in need else "",
                "balance": (
                    Decimal(dec(txn.balance_enc, "txn.balance"))
                    if "balance" in need and txn.balance_enc is not None
                    else None
                ),
            }
        )
    return rows


def first_transaction_date(user) -> date | None:
    """The date of the user's oldest transaction, or None if they have none."""
    return Transaction.objects.filter(user=user).aggregate(first=Min("date"))["first"]


def _error(code: str, detail: str) -> dict:
    return {"error": {"code": code, "detail": detail}}


def _effective_filters(panel: dict, dashboard: dict) -> dict:
    """A panel's own type / categories / merchant text win; empty ones use the dashboard bar's."""
    return {
        "type": panel["type"] or dashboard["type"],
        "categories": panel["categories"] or dashboard["categories"],
        "merchant_contains": panel["merchant_contains"] or dashboard["merchant_contains"],
    }


def _fields_needed(spec: dict, filters: dict) -> set:
    """The optional row fields this panel reads (amount is always loaded)."""
    fields = (spec.get("x", {}).get("field"), spec.get("color", {}).get("field"))
    need = set()
    if "merchant" in fields or filters["merchant_contains"]:
        need.add("name")
    if spec["y"]["measure"] == "balance":
        need.add("balance")
    return need


def _matching(rows: list[dict], filters: dict) -> list[dict]:
    """Apply one panel's filters in Python. The DB only did the broad cut for the whole batch."""
    needle = filters["merchant_contains"].lower()
    return [
        row
        for row in rows
        if (not filters["type"] or row["txn_type"] == filters["type"])
        and (not filters["categories"] or row["category_id"] in filters["categories"])
        and (not needle or needle in row["name"].lower())  # name is encrypted: only Python can look
    ]


def run_queries(user, global_filters: dict, queries: list[dict], today: date | None = None) -> dict:
    """Run every panel's spec against one shared load of the user's rows.

    `queries` is [{"key": ..., "spec": ...}]. Returns {key: result | {"error": {...}}}, so one
    bad panel never breaks the others. Raises SpecError only if `global_filters` is invalid.
    """
    today = today or timezone.localdate()
    dashboard = validate_filters(global_filters)
    first = first_transaction_date(user)

    results, plans = {}, {}
    for query in queries:
        key = query["key"]
        try:
            spec = validate_spec(query["spec"])
            period = resolve_period(spec["filters"]["date"], dashboard["date"], today)
        except SpecError as problem:
            results[key] = _error(problem.code, problem.detail)
            continue

        start, end = period
        if start == MIN_DATE:  # the "all" preset: begin at the user's first transaction instead
            start = min(first, end) if first else end
        # A KPI that compares needs the previous period's rows too, so it loads further back.
        load_start = engine.previous_period((start, end))[0] if spec["compare"] else start
        filters = _effective_filters(spec["filters"], dashboard)
        plans[key] = {
            "spec": spec,
            "period": (start, end),
            "load_start": load_start,
            "filters": filters,
            "need": _fields_needed(spec, filters),
        }

    if not plans:
        return results

    # One load for the whole batch. If any panel has no type / category filter, the DB can't
    # narrow on it; otherwise it narrows to the union of what the panels ask for.
    types = {plan["filters"]["type"] for plan in plans.values()}
    categories = [plan["filters"]["categories"] for plan in plans.values()]
    try:
        rows = load_rows(
            user,
            min(plan["load_start"] for plan in plans.values()),
            max(plan["period"][1] for plan in plans.values()),
            types=() if None in types else tuple(types),
            category_ids=(
                () if not all(categories) else tuple({c for ids in categories for c in ids})
            ),
            need=frozenset().union(*(plan["need"] for plan in plans.values())),
        )
    except TooManyRows:
        detail = "Too many transactions in the period. Pick a shorter date range or add filters."
        return results | {key: _error("too_many_rows", detail) for key in plans}

    for key, plan in plans.items():
        start, end = plan["period"]
        try:
            results[key] = {
                **engine.run(plan["spec"], _matching(rows, plan["filters"]), plan["period"]),
                # The dates the panel covers, so a click can open /transactions for them.
                "period": {"from": start.isoformat(), "to": end.isoformat()},
            }
        except engine.TooManyBuckets:
            results[key] = _error(
                "too_many_points",
                "Too many points to chart. Pick a coarser granularity or a shorter period.",
            )
    return results


# One context string per encrypted field: it is bound into the ciphertext, so a title blob
# can't be pasted into the name column. Same idea as "txn.name" / "txn.amount".
DASHBOARD_NAME = "dash.name"
PANEL_TITLE = "panel.title"
PANEL_CONFIG = "panel.config"


def encrypt_text(cipher, text: str, context: str) -> bytes:
    return cipher.encrypt(text.encode(), context)


def decrypt_text(cipher, blob, context: str) -> str:
    return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview


def encrypt_config(cipher, spec: dict) -> bytes:
    """Validate a panel spec, then encrypt the clean version. Raises SpecError."""
    clean = validate_spec(spec)
    return cipher.encrypt(json.dumps(clean, separators=(",", ":")).encode(), PANEL_CONFIG)


def decrypt_config(cipher, blob) -> dict:
    """Decrypt a saved config and validate it again, so an old shape can't reach the engine."""
    return validate_spec(json.loads(cipher.decrypt(bytes(blob), PANEL_CONFIG)))


def create_from_template(user, cipher, name: str, template: str, position: int) -> Dashboard:
    """A new dashboard filled with a template's panels, all or nothing."""
    with transaction.atomic():
        dashboard = Dashboard.objects.create(
            user=user,
            name_enc=encrypt_text(cipher, name, DASHBOARD_NAME),
            position=position,
        )
        Panel.objects.bulk_create(
            [
                Panel(
                    dashboard=dashboard,
                    title_enc=encrypt_text(cipher, panel["title"], PANEL_TITLE),
                    config_enc=encrypt_config(cipher, panel["config"]),  # validated here
                    x=panel["x"],
                    y=panel["y"],
                    w=panel["w"],
                    h=panel["h"],
                )
                for panel in TEMPLATES[template]
            ]
        )
    return dashboard
