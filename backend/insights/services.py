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
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

from transactions.models import Transaction
from vault.services import UserCipher

from . import engine
from .formula import FORMULA, days_in, fields_used
from .models import Dashboard, Panel
from .spec import (
    MIN_DATE,
    SpecError,
    apply_parameters,
    resolve_period,
    validate_filters,
    validate_parameters,
    validate_selection,
    validate_spec,
)
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
    `need` only when a panel uses them, so we skip decrypting what nobody looks at. "id" adds
    each row's primary key, for a stable order where rows are paged.
    """
    queryset = Transaction.objects.filter(user=user, date__range=(start, end))
    if types:
        queryset = queryset.filter(txn_type__in=types)
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)

    # Count BEFORE fetching or decrypting anything, so a huge range costs one cheap query.
    if queryset.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows(f"More than {settings.INSIGHTS_MAX_ROWS} transactions in the period.")

    cipher = UserCipher(user)  # one DEK load for every row

    def dec(blob, context):
        return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview

    want_name, want_balance, want_id = "name" in need, "balance" in need, "id" in need
    # Plain tuples, not model objects: building a Transaction per row was most of the time at
    # 20k rows on a slow CPU. No ORDER BY either: the engine sorts by date itself.
    columns = ["date", "txn_type", "category_id", "category__name", "amount_enc"]
    columns += ["name_enc"] if want_name else []
    columns += ["balance_enc"] if want_balance else []
    columns += ["id"] if want_id else []

    rows = []
    for values in queryset.order_by().values_list(*columns):
        day, txn_type, category_id, category_name, amount_enc, *optional = values
        name_enc = optional.pop(0) if want_name else None
        balance_enc = optional.pop(0) if want_balance else None
        row = {
            "date": day,
            "txn_type": txn_type,
            "category_id": str(category_id),  # for each panel's own category filter
            "category_name": category_name,
            "amount": Decimal(dec(amount_enc, "txn.amount")),
            "name": dec(name_enc, "txn.name") if want_name else "",
            "balance": (
                Decimal(dec(balance_enc, "txn.balance")) if balance_enc is not None else None
            ),
        }
        if want_id:
            row["id"] = optional.pop(0)
        rows.append(row)
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
    if spec["y"]["measure"] == FORMULA:  # [Merchant] needs the name, [Balance] the balance
        need |= fields_used(spec["y"]["formula"]["expression"])
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


def _normal_merchant(name: str) -> str:
    """A merchant name as the charts group it (engine.dimension_key)."""
    return " ".join(name.split()).title()


def _selected(rows: list[dict], selection: dict) -> list[dict]:
    """The rows a click stands for. The date range is not applied here: it narrows a panel's
    period instead (see _narrow), so a KPI still has earlier rows to compare with."""
    categories = {name.lower() for name in selection.get("categories", ())}
    merchants = {_normal_merchant(name) for name in selection.get("merchants", ())}
    weekdays, months = selection.get("weekdays"), selection.get("months")
    kind = selection.get("type")
    return [
        row
        for row in rows
        if (not kind or row["txn_type"] == kind)
        and (not categories or row["category_name"].lower() in categories)
        and (not merchants or _normal_merchant(row["name"]) in merchants)
        and (not weekdays or row["date"].weekday() in weekdays)
        and (not months or row["date"].month in months)
    ]


def _day_keys(*selections: dict) -> tuple[set | None, set | None]:
    """The weekdays and months that every selection allows (None: any)."""
    weekdays = months = None
    for selection in selections:
        if selection.get("weekdays"):
            picked = set(selection["weekdays"])
            weekdays = picked if weekdays is None else weekdays & picked
        if selection.get("months"):
            picked = set(selection["months"])
            months = picked if months is None else months & picked
    return weekdays, months


def _narrow(period: tuple[date, date], selection: dict) -> tuple[date, date] | None:
    """The period cut down to the selection's date range, or None if they don't overlap."""
    span = selection.get("date")
    if not span:
        return period
    start = max(period[0], date.fromisoformat(span["from"]))
    end = min(period[1], date.fromisoformat(span["to"]))
    return (start, end) if start <= end else None


def run_queries(
    user,
    global_filters: dict,
    queries: list[dict],
    today: date | None = None,
    parameters: dict | None = None,
    selection: dict | None = None,
    selection_source: str | None = None,
) -> dict:
    """Run every panel's spec against one shared load of the user's rows.

    `queries` is [{"key": ..., "spec": ...}]. Returns {key: result | {"error": {...}}}, so one
    bad panel never breaks the others. Raises SpecError only if `global_filters`,
    `parameters` or `selection` is invalid.

    `selection` (a clicked mark, see spec.validate_selection) narrows every panel except the
    one it came from (`selection_source`), which keeps showing everything so the context stays.
    """
    today = today or timezone.localdate()
    dashboard = validate_filters(global_filters)
    parameters = validate_parameters(parameters)
    selection = validate_selection(selection)
    first = first_transaction_date(user)

    results, plans = {}, {}
    for query in queries:
        key = query["key"]
        try:
            spec = apply_parameters(validate_spec(query["spec"]), parameters)
            if spec["chart"] == "text":  # a note has nothing to query
                results[key] = {"columns": [], "rows": [], "meta": {"chart": "text"}}
                continue
            period = resolve_period(spec["filters"]["date"], dashboard["date"], today)
        except SpecError as problem:
            results[key] = _error(problem.code, problem.detail)
            continue

        start, end = period
        if start == MIN_DATE:  # the "all" preset: begin at the user's first transaction instead
            start = min(first, end) if first else end
        picked = selection if key != selection_source else {}
        narrowed = _narrow((start, end), picked)
        blank = narrowed is None  # the clicked dates miss this panel's period entirely
        start, end = narrowed or (start, end)
        # A KPI that compares, or a calculation that looks back, needs earlier rows too.
        load_start = engine.load_start(spec, (start, end))
        filters = _effective_filters(spec["filters"], dashboard)
        need = _fields_needed(spec, filters)
        if picked.get("merchants"):
            need.add("name")
        plans[key] = {
            "spec": spec,
            "period": (start, end),
            "load_start": load_start,
            "filters": filters,
            "picked": picked,
            "blank": blank,
            "need": need,
            # A share of income is set against income whatever the panel's type filter says.
            "needs_all_types": "share_of_income" in spec.get("kpi", {}).get("secondary", ()),
        }

    if not plans:
        return results

    # One load for the whole batch. If any panel has no type / category filter, the DB can't
    # narrow on it; otherwise it narrows to the union of what the panels ask for.
    types = {plan["filters"]["type"] for plan in plans.values()}
    if any(plan["needs_all_types"] for plan in plans.values()):
        types.add(None)  # None means "every type": the DB can't narrow
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
            own = [] if plan["blank"] else _selected(_matching(rows, plan["filters"]), plan["picked"])
            all_types = (
                _selected(_matching(rows, {**plan["filters"], "type": None}), plan["picked"])
                if plan["needs_all_types"] and not plan["blank"]
                else None
            )
            results[key] = {
                **engine.run(plan["spec"], own, plan["period"], all_types),
                # The dates the panel covers, so a click can open /transactions for them.
                "period": {"from": start.isoformat(), "to": end.isoformat()},
            }
        except engine.PeriodTooLong:
            results[key] = _error("period_too_long", "Pick a period of a year or less.")
        except engine.TooManyBuckets:
            results[key] = _error(
                "too_many_points",
                "Too many points to chart. Pick a coarser granularity or a shorter period.",
            )
    return results


ROWS_PAGE_MAX = 100


def _money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def list_rows(
    user,
    global_filters: dict,
    spec: dict,
    mark: dict | None = None,
    parameters: dict | None = None,
    offset: int = 0,
    limit: int = 50,
    today: date | None = None,
    selection: dict | None = None,
) -> dict:
    """The transactions behind a chart mark, newest first, one page at a time.

    The same rules as the chart: the panel's period and filters (the dashboard's where the panel
    has none of its own), its parameters, and only the rows that count towards its measure (a
    spend chart lists debits). `mark` narrows it to what was clicked, and `selection` to a click
    that is filtering the dashboard (as run_queries applies it to this panel). `value` is the
    panel's measure over those rows, before any table calculation, so the list agrees with the
    bar. The order is newest first, and stable, so pages never repeat or skip a row. Raises
    SpecError for a bad spec, filters, mark or selection, and TooManyRows past INSIGHTS_MAX_ROWS.
    """
    today = today or timezone.localdate()
    dashboard = validate_filters(global_filters)
    parameters = validate_parameters(parameters)
    mark = validate_selection(mark)
    selection = validate_selection(selection)
    spec = apply_parameters(validate_spec(spec), parameters)
    if spec["chart"] == "text":
        raise SpecError("invalid_spec", "A note has no transactions.")

    start, end = resolve_period(spec["filters"]["date"], dashboard["date"], today)
    if start == MIN_DATE:  # the "all" preset: begin at the user's first transaction instead
        first = first_transaction_date(user)
        start = min(first, end) if first else end
    period = _narrow((start, end), selection)
    period = period and _narrow(period, mark)
    shown = period or (start, end)

    measure = spec["y"]["measure"]
    filters = _effective_filters(spec["filters"], dashboard)
    rows = []
    if period is not None:
        rows = load_rows(
            user,
            *period,
            types=(filters["type"],) if filters["type"] else (),
            category_ids=tuple(filters["categories"]),
            need=frozenset({"name", "id"} | _fields_needed(spec, filters)),
        )
        rows = _selected(_selected(_matching(rows, filters), selection), mark)
        if measure != FORMULA:  # a formula reads every transaction, whatever its type
            rows = [row for row in rows if engine.measure_value(row, measure) is not None]
    rows.sort(key=lambda row: (row["date"], row["amount"], row["id"]), reverse=True)

    page = rows[offset : offset + min(limit, ROWS_PAGE_MAX)]
    return {
        "total": len(rows),
        "value": engine.value_of(
            rows, spec["y"], partial(days_in, *shown, *_day_keys(selection, mark))
        ),
        "totals": {
            kind: _money(sum((row["amount"] for row in rows if row["txn_type"] == kind), Decimal(0)))
            for kind in ("debit", "credit")
        },
        "period": {"from": shown[0].isoformat(), "to": shown[1].isoformat()},
        "rows": [
            {
                "date": row["date"].isoformat(),
                "name": row["name"],
                "category": row["category_name"],
                "txn_type": row["txn_type"],
                "amount": _money(row["amount"]),
            }
            for row in page
        ],
    }


# One context string per encrypted field: it is bound into the ciphertext, so a title blob
# can't be pasted into the name column. Same idea as "txn.name" / "txn.amount".
DASHBOARD_NAME = "dash.name"
PANEL_TITLE = "panel.title"
DASHBOARD_SETTINGS = "dash.settings"
PANEL_CONFIG = "panel.config"


def encrypt_text(cipher, text: str, context: str) -> bytes:
    return cipher.encrypt(text.encode(), context)


def decrypt_text(cipher, blob, context: str) -> str:
    return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview


def encrypt_config(cipher, spec: dict) -> bytes:
    """Validate a panel spec, then encrypt the clean version. Raises SpecError."""
    clean = validate_spec(spec)
    return cipher.encrypt(json.dumps(clean, separators=(",", ":")).encode(), PANEL_CONFIG)


def encrypt_parameters(cipher, parameters: dict) -> bytes:
    """The parameter values as the dashboard's encrypted settings (validated here)."""
    settings_ = {"parameters": validate_parameters(parameters)}
    return cipher.encrypt(json.dumps(settings_).encode(), DASHBOARD_SETTINGS)


def decrypt_parameters(cipher, blob) -> dict:
    """A dashboard's parameter values; every one at its default when none were ever saved."""
    if blob is None:
        return validate_parameters({})
    stored = json.loads(cipher.decrypt(bytes(blob), DASHBOARD_SETTINGS))
    return validate_parameters(stored.get("parameters"))


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
