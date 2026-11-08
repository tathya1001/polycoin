"""Keeps a small model's reply to what the request actually asked for.

Asked for "every key", a 3B model tends to fill keys the request never mentions (a running
total, a colour split, a debit filter, a top 10, a made-up merchant). It also leaves out keys the
request does name: the measures in the order given ("spend vs income"), a calculation
("cumulative"), a KPI comparison ("against last month"), a split, a heatmap's second field. And
it turns some plain chart requests away as "not a chart". On the evaluation set these were the
most common reasons for a wrong panel.

As with the date phrase (compile.py), the request's own words decide, because code reads them more
reliably than the model:
- an optional key is kept only when the latest message, or the panel from an earlier turn,
  supports it; otherwise it is dropped, with a note;
- a key the message names plainly wins over the model's: the measures, the chart, a calculation,
  a KPI comparison, the x axis, a colour split and a heatmap's rows;
- a chart that can't show what the message names (a KPI card can't show "by day of the week")
  gives way to the default chart for it, unless the message names that chart;
- a turn-away is overruled only when the words name a measure and how to show it, and the message
  doesn't start like a question about reasons, advice or a single transaction.
"""

import re

from insights.spec import AVERAGE_OF_RANGE, CHART_RULES, MAX_EXTRA_MEASURES, WINDOW_RANGE

from .schema import PanelIntent

_I = re.IGNORECASE

# The words that support each optional key.
CALC_WORDS = re.compile(
    r"running|cumulative|so far|percent|percentage|share|% of|change|difference|growth|"
    r"moving|rolling|rank",
    _I,
)
TOP_WORDS = re.compile(
    r"\btop\b|\b(?:biggest|largest|highest|smallest|lowest|most|least)\s+\d+\b|"
    r"\b\d+\s+(?:biggest|largest|highest|smallest|lowest|most|least)\b|\bfirst \d+\b",
    _I,
)
SORT_WORDS = re.compile(r"\bsort|\border\b|alphabet|\bby name\b|\ba ?(?:to|-) ?z\b", _I)
TYPE_WORDS = re.compile(r"\bdebit|\bcredit|\bmoney (?:in|out)\b", _I)
COMPARE_WORDS = re.compile(
    r"compar|\bvs\.?\b|versus|against|than|previous|year ago|last (?:month|year)|average", _I
)
DIRECTION_WORDS = re.compile(r"\bgood\b|\bbad\b|\bbetter\b|\bworse\b", _I)
FIELD_WORDS = {
    "category": re.compile(r"categor", _I),
    "merchant": re.compile(r"merchant|\bshops?\b|\bstores?\b|payee", _I),
    "txn_type": re.compile(r"\btype\b|\bdebit|\bcredit|money (?:in|out)|in and out", _I),
    "data_source": re.compile(r"\bsources?\b|\baccounts?\b|\bbanks?\b|\bcards?\b", _I),
    "weekday": re.compile(r"day of (?:the )?week|weekday", _I),
    "month_of_year": re.compile(r"month of (?:the )?year", _I),
}
MEASURE_WORDS = {
    "spend": re.compile(r"\bspen[dt]|spending|expens|outgo|money out", _I),
    "income": re.compile(r"income|earn|salary|money in", _I),
    "net": re.compile(r"\bnet\b|saving", _I),
    "amount": re.compile(r"\bamount", _I),
    "count": re.compile(r"\bcount|number of|how many", _I),
    "balance": re.compile(r"balance", _I),
}
# Measures joined like this are all shown: "spend vs income", "spend, income and net".
MEASURE_JOIN = re.compile(
    r"\s*(?:,\s*(?:and\s+)?|and|&|vs\.?|versus|against|plus)\s*(?:my\s+)?", _I
)
IN_AND_OUT = re.compile(r"\bin (?:and|&|vs\.?) out\b", _I)  # one amount, split by type
ADD_WORDS = re.compile(r"\badd\b|\balso\b|\btoo\b|\bas well\b", _I)
# The x axis a message names, most specific first: "by month of the year" is not "by month".
X_WORDS = [
    ("month_of_year", None, FIELD_WORDS["month_of_year"]),
    ("weekday", None, FIELD_WORDS["weekday"]),
    ("date", "day", re.compile(r"\bdaily\b|\b(?:each|per|by|every) day\b|day over day", _I)),
    ("date", "week", re.compile(r"\bweekly\b|\b(?:each|per|by|every) week\b|week over week", _I)),
    ("date", "month", re.compile(r"\bmonthly\b|\b(?:each|per|by|every) month\b|month over month", _I)),
    ("date", "year", re.compile(r"\byearly\b|\bannual|\b(?:each|per|by|every) year\b|year over year", _I)),
    ("category", None, re.compile(r"\b(?:by|per|each|every|across) categor", _I)),
    ("merchant", None, re.compile(r"merchants|\b(?:by|per|each|every) (?:merchant|shop|store|payee)", _I)),
]  # fmt: skip
COLOR_WORDS = re.compile(
    r"(?:split|broken down|break(?:ing)? down|stacked|colou?red)\s+(?:by|into)\s+"
    r"(categor|merchant|type|source)",
    _I,
)
COLOR_FIELDS = {"categor": "category", "merchant": "merchant", "type": "txn_type",
                "source": "data_source"}  # fmt: skip
# A chart the message names. Only one may be named: "bars instead of lines" is left to the model.
CHART_NAMES = (
    ("heatmap", re.compile(r"heat ?map", _I)),
    ("histogram", re.compile(r"histogram", _I)),
    ("donut", re.compile(r"donut|doughnut", _I)),
    ("pie", re.compile(r"\bpie\b", _I)),
    ("area", re.compile(r"\barea (?:chart|graph)\b|\bas (?:an )?area\b", _I)),
    ("line", re.compile(r"\blines?\b", _I)),
    ("bar", re.compile(r"\bbars?\b", _I)),
    ("calendar", re.compile(r"\bcalendar\b", _I)),
    ("kpi", re.compile(r"\bkpi\b|\b(?:number|summary) card\b|single number", _I)),
)
# A table calculation the message names plainly.
CALC_PHRASES = (
    ("running_total", re.compile(r"running total|cumulative", _I)),
    ("percent_of_total", re.compile(r"percent(?:age)? of (?:the |my )?total|share of|% of", _I)),
    ("moving_average", re.compile(r"moving average|rolling average", _I)),
    ("change", re.compile(r"\b(day|week|month|year) over \1\b|\bchange in\b|\bgrowth\b", _I)),
)
OVER_TIME_CALCS = ("running_total", "moving_average", "change")  # they need dates along x
WINDOW_WORDS = re.compile(r"\b(\d{1,2})[- ]?(day|week|month)s?\b", _I)
# A KPI comparison the message names plainly; "a year ago" is checked before "last year".
COMPARE_PHRASES = (
    (
        "year_ago",
        re.compile(
            r"year ago|year earlier|same (?:day|week|month|period) (?:last|a|the previous) year", _I
        ),
    ),
    ("average", re.compile(r"(?:compar\w*|\bvs\.?|versus|against)\b[^.?!]*\baverage\b", _I)),
    (
        "previous",
        re.compile(
            r"(?:compar\w*(?: (?:with|to))?|\bvs\.?|versus|against|than) (?:the |my )?"
            r"(?:last|previous|prior) (?:day|week|month|year|period)",
            _I,
        ),
    ),
)
AVERAGE_OF_WORDS = re.compile(r"\b(\d{1,2})[- ]?months?(?:'s?)? average", _I)
# How a message starts when it asks for a reason, advice, an action or one transaction.
ASKS_SOMETHING_ELSE = re.compile(
    r"^\s*(?:why|should|shall|can|could|would|will|am|is|are|do|does|did|what|which|who|when|"
    r"where|explain|tell|make|write|send|move|transfer|pay|delete|remove|ignore|help|give)\b",
    _I,
)
HOW_MUCH = re.compile(r"^\s*how (?:much|many)\b", _I)

EMPTY_REPLY = (
    "The reply is a panel but sets no chart, measure or x axis. Read the request again and give "
    "the keys it asks for."
)
READ_AS_PANEL = "The request names a measure and how to show it, so it was built as a chart."


_WORD = re.compile(r"[^\W_]{3,}")
# Words that name no particular merchant, so they can't support one ("Top 5 merchants" doesn't
# support a made-up "Merchant 1").
GENERIC_WORDS = frozenset(
    "merchant merchants shop shops store stores payee payees spend spent spending money paid pay "
    "payment payments transaction transactions top most month months year years week weeks day "
    "days last this each every total".split()
)


def mentions_merchant(message: str, merchant: str) -> bool:
    """True if a meaningful word of the message and of the merchant overlap, either way round:
    "tasty" supports "Tastybites", and "Tastybites Cafe" supports "tastybites"."""
    said = {w for w in _WORD.findall(message.casefold()) if w not in GENERIC_WORDS}
    named = {w for w in _WORD.findall(merchant.casefold()) if w not in GENERIC_WORDS}
    return any(a in b or b in a for a in said for b in named)


def says_nothing(intent: PanelIntent) -> bool:
    """A "panel" that sets none of its main keys: a copied example, not an answer."""
    return intent.kind == "panel" and not any(
        (intent.chart, intent.measure, intent.x, intent.also_measures, intent.calc, intent.limit)
    )


def named_x(message: str) -> tuple[str, str | None] | None:
    """(field, granularity or None) for an x axis the message names plainly, else None."""
    for field, granularity, words in X_WORDS:
        if words.search(message):
            return field, granularity
    return None


def named_measures(message: str) -> tuple[str, ...]:
    """The measures the message names: the first one, then each one joined to it ("spend vs
    income"), in the message's order. Empty if it names none, or asks for money "in and out"
    (one amount, split by type)."""
    if IN_AND_OUT.search(message):
        return ()
    spans = []
    for name, words in MEASURE_WORDS.items():
        if found := words.search(message):
            end = found.end()
            while end < len(message) and message[end].isalnum():
                end += 1  # to the end of the word: "Earnings", not "Earn"
            spans.append((found.start(), end, name))
    spans.sort()
    if len(spans) > 1:  # "my spending amounts" is spend
        spans = [span for span in spans if span[2] != "amount"]
    if not spans:
        return ()
    chosen = [spans[0][2]]
    for (_, end, _), (start, _, name) in zip(spans, spans[1:]):
        if not MEASURE_JOIN.fullmatch(message[end:start]):
            break
        chosen.append(name)
    return tuple(chosen)


def named_chart(message: str) -> str | None:
    named = [chart for chart, words in CHART_NAMES if words.search(message)]
    return named[0] if len(named) == 1 else None


def named_calc(message: str) -> str | None:
    return next((calc for calc, words in CALC_PHRASES if words.search(message)), None)


def named_compare(message: str) -> str | None:
    return next((compare for compare, words in COMPARE_PHRASES if words.search(message)), None)


def named_fields(message: str) -> list[str]:
    """The categorical fields the message names, in its order."""
    found = [
        (match.start(), field)
        for field, words in FIELD_WORDS.items()
        if (match := words.search(message))
    ]
    return [field for _, field in sorted(found)]


def overrule_refusal(message: str) -> PanelIntent | None:
    """A panel for a request the model turned away, when its words plainly ask for one: a measure
    and an axis, a chart or a calculation ("spend by day of the week"), or "how much" with a
    measure ("how much income did I get last month?"). None when the model's call stands."""
    measures = named_measures(message)
    if not measures or ASKS_SOMETHING_ELSE.match(message):
        return None
    how_much, x, chart = HOW_MUCH.match(message), named_x(message), named_chart(message)
    if not (how_much or x or chart or named_calc(message)):
        return None
    field, granularity = x or (None, None)
    return PanelIntent(
        kind="panel",
        chart=chart or ("kpi" if how_much and not x else None),
        measure=measures[0],
        also_measures=list(measures[1:]),
        x=field,
        granularity=granularity,
    )


def rein_in(
    intent: PanelIntent, message: str, previous: dict | None
) -> tuple[PanelIntent, list[str]]:
    """The intent with unsupported optional keys dropped and the keys the message names applied,
    and the notes saying what changed. `previous` is the panel from an earlier turn, whose keys
    stay supported."""
    if intent.kind != "panel":
        return intent, []
    previous = previous or {}
    update, notes = {}, []

    def now(key: str):
        return update.get(key, getattr(intent, key))

    def supported(key: str, value, words: re.Pattern | None) -> bool:
        return value == previous.get(key) or bool(words and words.search(message))

    # Keys the request doesn't support are dropped.
    if intent.calc and not supported("calc", intent.calc, CALC_WORDS):
        update.update(calc=None, window=None, change_vs=None, change_as=None)
        notes.append("The request asks for no calculation, so none was added.")
    if intent.limit is not None and not supported("limit", intent.limit, TOP_WORDS):
        update["limit"] = None
        notes.append("The request asks for no top N, so every value is shown.")
    if intent.sort is not None and not supported("sort", intent.sort, SORT_WORDS):
        update["sort"] = None
    if intent.txn_type and not supported("txn_type", intent.txn_type, TYPE_WORDS):
        update["txn_type"] = None
        notes.append("The request names no credit or debit filter, so none was added.")
    if intent.compare not in (None, "none") and not supported(
        "compare", intent.compare, COMPARE_WORDS
    ):
        update.update(compare=None, average_of=None)
    if intent.direction and not supported("direction", intent.direction, DIRECTION_WORDS):
        update["direction"] = None
    for key in ("color", "rows"):
        field = getattr(intent, key)
        if field and not supported(key, field, FIELD_WORDS.get(field)):
            update[key] = None
            if key == "color":
                notes.append("The request asks for no split, so the panel has one colour.")
    if intent.merchant and not (
        intent.merchant == previous.get("merchant") or mentions_merchant(message, intent.merchant)
    ):
        update["merchant"] = None
        notes.append(f"The request names no merchant, so {intent.merchant!r} was left out.")

    # The measures, in the order the request names them.
    measures = named_measures(message)
    if measures and previous.get("measure") and ADD_WORDS.search(message):
        # "add income": the earlier panel's measures stay, and the named ones join them
        main = previous["measure"]
        also = [*previous.get("also_measures", []), *measures]
    elif measures:
        main, also = measures[0], list(measures[1:])
    else:
        main = intent.measure
        also = [m for m in intent.also_measures if MEASURE_WORDS[m].search(message)]
        if intent.also_measures == previous.get("also_measures"):
            also = intent.also_measures
    also = [m for m in dict.fromkeys(also) if m != main][:MAX_EXTRA_MEASURES]
    if main != intent.measure:
        update["measure"] = main
        if intent.measure:
            notes.append(f"The request asks for {main}, so the chart shows it.")
    if also != intent.also_measures:
        update["also_measures"] = also

    chart = named_chart(message)
    if chart and chart != intent.chart:
        update["chart"] = chart

    calc = named_calc(message)
    if calc and calc != now("calc"):
        update.update(calc=calc, window=None, change_vs=None, change_as=None)
    if now("calc") == "moving_average" and (window := WINDOW_WORDS.search(message)):
        size = int(window[1])
        if WINDOW_RANGE[0] <= size <= WINDOW_RANGE[1]:
            update["window"] = size
            if not named_x(message):
                update.update(x="date", granularity=window[2].lower())

    compare = named_compare(message)
    if compare and compare != now("compare"):
        update.update(compare=compare, average_of=None)
    if now("compare") == "average" and (months := AVERAGE_OF_WORDS.search(message)):
        size = int(months[1])
        if AVERAGE_OF_RANGE[0] <= size <= AVERAGE_OF_RANGE[1]:
            update["average_of"] = size
    if compare and not named_x(message) and not chart:
        # A comparison of one number with an earlier one is a KPI card.
        update.update(chart="kpi", x=None, granularity=None, color=None, calc=None)

    named = named_x(message)
    if named:
        field, granularity = named
        if now("x") != field:
            update["x"] = field
            notes.append(f"The request asks for {field.replace('_', ' ')} along the axis.")
        if granularity and now("granularity") != granularity:
            update["granularity"] = granularity
    if now("calc") in OVER_TIME_CALCS and now("x") is None:
        update["x"] = "date"
    split = COLOR_WORDS.search(message)
    if split and now("color") != COLOR_FIELDS[split[1].lower()]:
        update["color"] = COLOR_FIELDS[split[1].lower()]

    if now("chart") == "heatmap":
        fields = [f for f in named_fields(message) if f != now("x")]
        if fields and (now("rows") is None or now("rows") == now("x")):
            update["rows"] = fields[0]

    # A chart that can't show an axis or a split the request asks for gives way, unless the
    # request names that chart. An axis only the model picked is left for compile to drop.
    current = now("chart")
    if current and current != chart:
        rules = CHART_RULES[current]
        axis_asked = bool(named) or update.get("x") is not None
        x_ok = not axis_asked or now("x") is None or now("x") in rules["x"]
        color_ok = not split or now("color") == now("x") or rules["color"]
        if not (x_ok and color_ok):
            update["chart"] = None  # compile picks the default chart for that axis

    return (intent.model_copy(update=update) if update else intent), notes
