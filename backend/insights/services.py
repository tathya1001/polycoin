"""Where insights touches the database and the vault.

Charts: amounts are encrypted, so SQL can't add them up. Plain columns narrow the rows in
the DB first, then the survivors are decrypted in memory for this one request and handed to
the pure engine. Nothing is stored, cached or logged.

Dashboards: the encrypt / decrypt helpers for names, titles and panel configs, and the
builder for starter templates.
"""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import partial

from django.conf import settings
from django.db import transaction
from django.db.models import CharField, Max, Min
from django.db.models.functions import Cast
from django.utils import timezone

from datasources.services import sources_for
from transactions.models import Transaction, TransferLink
from vault.services import UserCipher

from . import engine
from .balances import BalanceBook, SourceLabel, closing_row
from .formula import (
    FORMULA,
    FormulaError,
    PanelView,
    Span,
    compile_expression,
    days_in,
    panel_view,
    parse_once,
    rename_source,
    source_key,
)
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


def source_labels(user, cipher) -> dict:
    """The user's data sources: {primary key: SourceLabel}."""
    return {
        source.pk: SourceLabel(str(source.pk), source.name, source_key(source.name))
        for source in sources_for(user, cipher)
    }


def _link_partners(user) -> dict:
    """{transaction id: the data source of the transaction it is linked to}."""
    partners = {}
    for debit, debit_source, credit, credit_source in TransferLink.objects.filter(
        user=user
    ).values_list("debit_id", "debit__data_source_id", "credit_id", "credit__data_source_id"):
        partners[debit] = str(credit_source)
        partners[credit] = str(debit_source)
    return partners


def load_rows(
    user,
    start: date,
    end: date,
    types: tuple = (),
    category_ids: tuple = (),
    need: frozenset = frozenset(),
    source_ids: tuple = (),
    cipher=None,
    labels: dict | None = None,
) -> list[dict]:
    """The user's transactions from `start` to `end` as the plain dicts the engine reads.

    `types`, `category_ids` and `source_ids` narrow the rows in the DB; empty means "don't
    filter". `amount` is always decrypted (every measure reads it). Pass "name" and/or "balance"
    in `need` only when a panel uses them, so we skip decrypting what nobody looks at. "id" adds
    each row's primary key, for a stable order where rows are paged, and "stored_order" returns
    rows in the order they were stored, which settles a balance. `cipher` and `labels` save a
    load when the caller has them.
    """
    queryset = Transaction.objects.filter(user=user, date__range=(start, end))
    if types:
        queryset = queryset.filter(txn_type__in=types)
    if category_ids:
        queryset = queryset.filter(category_id__in=category_ids)
    if source_ids:
        queryset = queryset.filter(data_source_id__in=source_ids)

    # Count BEFORE fetching or decrypting anything, so a huge range costs one cheap query.
    if queryset.count() > settings.INSIGHTS_MAX_ROWS:
        raise TooManyRows(f"More than {settings.INSIGHTS_MAX_ROWS} transactions in the period.")

    cipher = cipher or UserCipher(user)  # one DEK load for every row
    labels = source_labels(user, cipher) if labels is None else labels
    partners = _link_partners(user)

    def dec(blob, context):
        return cipher.decrypt(bytes(blob), context).decode()  # bytes(): Postgres gives memoryview

    want_name, want_balance = "name" in need, "balance" in need
    want_id = "id" in need or bool(partners)
    # Plain tuples, not model objects: building a Transaction per row was most of the time at
    # 20k rows on a slow CPU. No ORDER BY either, unless asked: the engine sorts by date itself.
    # The database does that sort, because turning 20k timestamps into Python ones is slower.
    # The source comes back as text for the same reason: a UUID object per row is not free.
    by_text = {label.id: label for label in labels.values()}
    queryset = queryset.annotate(source_text=Cast("data_source_id", CharField()))
    columns = ["date", "txn_type", "category_id", "category__name", "source_text", "amount_enc"]
    columns += ["name_enc"] if want_name else []
    columns += ["balance_enc"] if want_balance else []
    columns += ["id"] if want_id else []
    ordering = ("created_at",) if "stored_order" in need else ()

    rows = []
    for values in queryset.order_by(*ordering).values_list(*columns):
        day, txn_type, category_id, category_name, source_id, amount_enc, *optional = values
        name_enc = optional.pop(0) if want_name else None
        balance_enc = optional.pop(0) if want_balance else None
        row = {
            "date": day,
            "txn_type": txn_type,
            "category_id": str(category_id),  # for each panel's own category filter
            "category_name": category_name,
            "source": by_text[source_id],
            "link_source": None,  # the data source of the other side of a transfer
            "amount": Decimal(dec(amount_enc, "txn.amount")),
            "name": dec(name_enc, "txn.name") if want_name else "",
            "balance": (
                Decimal(dec(balance_enc, "txn.balance")) if balance_enc is not None else None
            ),
        }
        if want_id:
            row["id"] = optional.pop(0)
            row["link_source"] = partners.get(row["id"])
        rows.append(row)
    return rows


def first_transaction_date(user) -> date | None:
    """The date of the user's oldest transaction, or None if they have none."""
    return Transaction.objects.filter(user=user).aggregate(first=Min("date"))["first"]


def opening_balances(user, cipher, before: date, labels: dict) -> dict[str, Decimal]:
    """Each source's balance at the end of its last day with one before `before`.

    {source key: balance}. One small query per source, and only when a panel reads a balance.
    """
    balances = {}
    for source_id, label in labels.items():
        known = Transaction.objects.filter(
            data_source_id=source_id, date__lt=before, balance_enc__isnull=False
        ).order_by()
        day = known.aggregate(day=Max("date"))["day"]
        if day is None:
            continue
        rows = [
            {
                "txn_type": txn_type,
                "amount": Decimal(cipher.decrypt(bytes(amount), "txn.amount").decode()),
                "balance": Decimal(cipher.decrypt(bytes(balance), "txn.balance").decode()),
            }
            for txn_type, amount, balance in known.filter(date=day)
            .order_by("created_at")
            .values_list("txn_type", "amount_enc", "balance_enc")
        ]
        balances[label.key] = closing_row(rows)["balance"]
    return balances


def _error(code: str, detail: str) -> dict:
    return {"error": {"code": code, "detail": detail}}


def _effective_filters(panel: dict, dashboard: dict) -> dict:
    """A panel's own type / categories / merchant text win; empty ones use the dashboard bar's."""
    return {
        "type": panel["type"] or dashboard["type"],
        "categories": panel["categories"] or dashboard["categories"],
        "data_sources": panel["data_sources"] or dashboard["data_sources"],
        "merchant_contains": panel["merchant_contains"] or dashboard["merchant_contains"],
    }


def _fields_needed(spec: dict, filters: dict) -> set:
    """The optional row fields this panel reads (amount is always loaded)."""
    fields = (spec.get("x", {}).get("field"), spec.get("color", {}).get("field"))
    need = set()
    if "merchant" in fields or filters["merchant_contains"]:
        need.add("name")
    if spec["y"]["measure"] == "balance":
        need |= {"balance", "stored_order"}
    if spec["y"]["measure"] == FORMULA:  # [Merchant] needs the name, [Balance] the balance
        compiled = compile_expression(spec["y"]["formula"]["expression"])
        need |= compiled.fields
        if compiled.uses_balance:
            need.add("stored_order")
    return need


@dataclass(frozen=True, slots=True)
class SourceScope:
    """Which data sources one panel reads."""

    shown: frozenset | None  # the ids it shows; None means every source
    named: frozenset  # the ids its formula names, which it reads whatever `shown` says
    balance: bool  # it reads a balance, which needs a BalanceBook

    @property
    def wanted(self) -> frozenset | None:
        return None if self.shown is None else self.shown | self.named


def _scope_of(spec: dict, filters: dict, labels: dict) -> SourceScope:
    """Raises SpecError if the panel uses a data source that doesn't exist (any more)."""
    shown = frozenset(filters["data_sources"]) or None
    if shown and not shown <= {label.id for label in labels.values()}:
        raise SpecError(
            "unknown_data_source",
            "This panel uses a data source that no longer exists. Choose another one.",
        )
    named, reads_balance = frozenset(), spec["y"]["measure"] == "balance"
    if spec["y"]["measure"] == FORMULA:
        compiled = compile_expression(spec["y"]["formula"]["expression"])
        reads_balance = compiled.uses_balance
        ids = {label.key: label.id for label in labels.values()}
        for key in compiled.sources:
            if key not in ids:
                raise SpecError("unknown_data_source", f'There is no data source named "{key}".')
        named = frozenset(ids[key] for key in compiled.sources)
    return SourceScope(shown, named, reads_balance)


def _visible(shown: frozenset | None) -> callable:
    """Whether a row counts for a calculation over the sources `shown`.

    A transfer between two of the user's own sources cancels out when both sides are in view.
    The test is on the source, not on the other row being loaded, so a transfer that crosses
    the end of a period still cancels.
    """

    def visible(row: dict) -> bool:
        if shown is not None and row["source"].id not in shown:
            return False
        partner = row["link_source"]
        return partner is None or (shown is not None and partner not in shown)

    return visible


def _panel_rows(
    matched: list[dict],
    scope: SourceScope,
    picked: dict,
    openings: dict,
    labels: dict,
    linked: bool,
) -> tuple[list[dict], PanelView]:
    """A panel's rows after the data source rules, and the view its calculations need.

    `matched` has passed every other filter, and `linked` says whether any loaded row is part
    of a transfer. A balance reads the rows before transfers cancel: a transfer is a real change
    to what each source holds.
    """
    wanted = scope.wanted
    rows = matched if wanted is None else [r for r in matched if r["source"].id in wanted]

    book = None
    if scope.balance:
        keys = None
        if scope.shown is not None:
            keys = {label.key for label in labels.values() if label.id in scope.shown}
        if picked.get("data_sources"):
            chosen = {source_key(name) for name in picked["data_sources"]}
            every = {label.key for label in labels.values()}
            keys = chosen & (every if keys is None else keys)
        names = {label.key: label.name for label in labels.values()}
        book = BalanceBook(rows, openings, keys, names)

    visible = _visible(scope.shown)
    if scope.named:  # bare names skip rows that only a named source may read
        return rows, PanelView(book, visible)
    if scope.shown is None and not linked:
        return rows, PanelView(book)  # nothing to take away, so no extra pass over the rows
    return list(filter(visible, rows)), PanelView(book)


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
    sources = {source_key(name) for name in selection.get("data_sources", ())}
    weekdays, months = selection.get("weekdays"), selection.get("months")
    kind = selection.get("type")
    return [
        row
        for row in rows
        if (not kind or row["txn_type"] == kind)
        and (not categories or row["category_name"].lower() in categories)
        and (not merchants or _normal_merchant(row["name"]) in merchants)
        and (not sources or row["source"].key in sources)
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
    cipher = UserCipher(user)  # one DEK load for the names and every row
    labels = source_labels(user, cipher)

    results, plans = {}, {}
    for query in queries:
        key = query["key"]
        try:
            spec = apply_parameters(validate_spec(query["spec"]), parameters)
            if spec["chart"] == "text":  # a note has nothing to query
                results[key] = {"columns": [], "rows": [], "meta": {"chart": "text"}}
                continue
            period = resolve_period(spec["filters"]["date"], dashboard["date"], today)
            filters = _effective_filters(spec["filters"], dashboard)
            scope = _scope_of(spec, filters, labels)
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
        need = _fields_needed(spec, filters)
        if picked.get("merchants"):
            need.add("name")
        plans[key] = {
            "spec": spec,
            "period": (start, end),
            "load_start": load_start,
            "filters": filters,
            "scope": scope,
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
    wanted = [plan["scope"].wanted for plan in plans.values()]
    first_day = min(plan["load_start"] for plan in plans.values())
    try:
        rows = load_rows(
            user,
            first_day,
            max(plan["period"][1] for plan in plans.values()),
            types=() if None in types else tuple(types),
            category_ids=(
                () if not all(categories) else tuple({c for ids in categories for c in ids})
            ),
            need=frozenset().union(*(plan["need"] for plan in plans.values())),
            source_ids=() if None in wanted else tuple(frozenset().union(*wanted)),
            cipher=cipher,
            labels=labels,
        )
    except TooManyRows:
        detail = "Too many transactions in the period. Pick a shorter date range or add filters."
        return results | {key: _error("too_many_rows", detail) for key in plans}

    needs_balance = any(plan["scope"].balance for plan in plans.values())
    openings = opening_balances(user, cipher, first_day, labels) if needs_balance else {}
    linked = any(row["link_source"] for row in rows)

    for key, plan in plans.items():
        start, end = plan["period"]
        try:
            filters, scope, picked = plan["filters"], plan["scope"], plan["picked"]
            matched = [] if plan["blank"] else _selected(_matching(rows, filters), picked)
            own, view = _panel_rows(matched, scope, picked, openings, labels, linked)
            all_types = None
            if plan["needs_all_types"] and not plan["blank"]:
                all_types = _selected(_matching(rows, {**filters, "type": None}), picked)
                all_types = list(filter(_visible(scope.shown), all_types))
            results[key] = {
                **engine.run(plan["spec"], own, plan["period"], all_types, view),
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
    cipher = UserCipher(user)
    labels = source_labels(user, cipher)
    scope = _scope_of(spec, filters, labels)
    rows, view = [], None
    if period is not None:
        rows = load_rows(
            user,
            *period,
            types=(filters["type"],) if filters["type"] else (),
            category_ids=tuple(filters["categories"]),
            need=frozenset({"name", "id"} | _fields_needed(spec, filters)),
            source_ids=tuple(scope.wanted or ()),
            cipher=cipher,
            labels=labels,
        )
        linked = any(row["link_source"] for row in rows)
        rows = _selected(_selected(_matching(rows, filters), selection), mark)
        openings = opening_balances(user, cipher, period[0], labels) if scope.balance else {}
        rows, view = _panel_rows(rows, scope, {**selection, **mark}, openings, labels, linked)
        if measure != FORMULA:  # a formula reads every transaction, whatever its type
            rows = [row for row in rows if engine.measure_value(row, measure) is not None]
    rows.sort(key=lambda row: (row["date"], row["amount"], row["id"]), reverse=True)

    days = Span(partial(days_in, *shown, *_day_keys(selection, mark)), shown[1])
    with parse_once(), panel_view(view):
        value = engine.value_of(rows, spec["y"], days)

    page = rows[offset : offset + min(limit, ROWS_PAGE_MAX)]
    return {
        "total": len(rows),
        "value": value,
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
                "data_source": row["source"].name,
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


def _stored_configs(user, cipher) -> list[tuple[Panel, dict]]:
    """Every panel of the user with its config as saved, not validated: a panel whose settings
    no longer work must not stop a rename."""
    return [
        (panel, json.loads(cipher.decrypt(bytes(panel.config_enc), PANEL_CONFIG)))
        for panel in Panel.objects.filter(dashboard__user=user)
    ]


def _formula_text(config: dict) -> str | None:
    y = config.get("y")
    formula = y.get("formula") if isinstance(y, dict) else None
    return formula.get("expression") if isinstance(formula, dict) else None


def rename_source_in_panels(user, cipher, old: str, new: str) -> int:
    """Keeps formulas working after a data source is renamed. Returns how many panels changed."""
    changed = []
    for panel, config in _stored_configs(user, cipher):
        text = _formula_text(config)
        if not text:
            continue
        try:
            renamed = rename_source(text, old, new)
        except FormulaError:
            continue  # it was already broken: the panel says so when it runs
        if renamed != text:
            config["y"]["formula"]["expression"] = renamed
            clean = json.dumps(config, separators=(",", ":")).encode()
            panel.config_enc = cipher.encrypt(clean, PANEL_CONFIG)
            changed.append(panel)
    Panel.objects.bulk_update(changed, ["config_enc"])
    return len(changed)


def panels_using_source(user, cipher, source_id: str, name: str) -> int:
    """How many panels stop working if this data source goes."""
    key, count = source_key(name), 0
    for _, config in _stored_configs(user, cipher):
        filters = config.get("filters")
        used = isinstance(filters, dict) and source_id in (filters.get("data_sources") or ())
        text = _formula_text(config)
        if not used and text:
            try:
                used = key in compile_expression(text).sources
            except FormulaError:
                pass
        count += bool(used)
    return count


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
