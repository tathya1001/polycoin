"""Calculated fields: a small, safe expression language.

A panel can show a number it works out itself, such as a savings rate, or the share of the
spending that went on groceries:

    (income - spend) / income * 100
    SUM(IF [Category] = "Groceries" THEN [Spend] END) / spend * 100

There are two kinds of name. Totals (`spend`, `income`, `net`, `count`, `days`) hold one value
for the whole group (a month, a category...). Fields in brackets (`[Amount]`, `[Category]`,
`[Date]`...) hold one value per transaction, so they can only be used inside an
aggregation such as SUM() or COUNTD(). The language also has comparisons, AND / OR / NOT,
IF ... THEN ... ELSE ... END, CASE WHEN, IN (...), text in quotes, and the functions listed in
FUNCTIONS below. Keywords and names do not depend on letter case.

A value can be missing (NULL): a debit has no [Income], and dividing by zero has no answer.
Missing values spread through arithmetic, aggregations skip them, and an IF treats a missing
condition as false. SUM and COUNT of nothing are 0, the same as the totals and the chart
measures; AVG, MEDIAN, MIN and MAX of nothing are missing.

The text is never passed to eval() or exec(). It is split into tokens and parsed into a tree by
a recursive-descent parser (the classic way to read arithmetic). The tree is then checked
(types, and which parts are per transaction) and turned into plain Python functions that work
with Decimal numbers. The limits below bound the work any one formula can cost: a request
cannot make the server spin by sending a long or deeply nested formula.
"""

import operator
import re
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

FORMULA = "formula"  # the y.measure value of a panel that shows a calculated field
RESULT_FORMS = ("number", "percent", "money")

MAX_LENGTH = 500  # characters
MAX_TOKENS = 200
MAX_DEPTH = 12  # nested brackets, function calls, IFs, NOTs and minus signs
MAX_DIGITS = 12  # in one number
MAX_STRING = 100  # characters in one quoted text
MAX_ARGS = 10  # values in one function call
MAX_IN_ITEMS = 50  # values in one IN (...)
MAX_POWER = 100  # POWER(x, y) accepts y from -MAX_POWER to MAX_POWER
MAX_PLACES = 6  # ROUND(x, places) accepts places from 0 to MAX_PLACES
# A bigger result cannot be stored to the cent in a Decimal (28 digits) and means a mistake.
MAX_RESULT = Decimal("1e15")

KEYWORDS = (
    "IF", "THEN", "ELSEIF", "ELSE", "END", "CASE", "WHEN",
    "AND", "OR", "NOT", "IN", "TRUE", "FALSE", "NULL",
)  # fmt: skip

# The types a part of a formula can have, and how messages name them.
NUMBER, TEXT, DATE, BOOL, NULL = "number", "text", "date", "bool", "null"
_TYPE_WORDS = {NUMBER: "a number", TEXT: "text", DATE: "a date", BOOL: "true/false", NULL: "NULL"}

# Whether a part has one value for the whole formula, one per transaction, or one per group.
CONST, ROW, TOTAL = 0, 1, 2


class FormulaError(ValueError):
    """The formula cannot be used. The message says what is wrong and where."""


# --- the names ---------------------------------------------------------------------------------


def _merchant(row: dict) -> str:
    return " ".join(row["name"].split()).title()  # the same as the merchant dimension


# name -> (type, optional row field it needs decrypted, reader, help). The readers give the same
# values as engine.measure_value and engine.dimension_key; the tests hold them to that.
FIELDS = {
    "Amount": (NUMBER, None, lambda row: row["amount"], "The amount, always positive."),
    "Spend": (
        NUMBER,
        None,
        lambda row: row["amount"] if row["txn_type"] == "debit" else None,
        "The amount of a debit. Missing for a credit.",
    ),
    "Income": (
        NUMBER,
        None,
        lambda row: None if row["txn_type"] == "debit" else row["amount"],
        "The amount of a credit. Missing for a debit.",
    ),
    "Net": (
        NUMBER,
        None,
        lambda row: -row["amount"] if row["txn_type"] == "debit" else row["amount"],
        "The amount, negative for a debit.",
    ),
    "Type": (TEXT, None, lambda row: row["txn_type"], '"debit" or "credit".'),
    "Category": (TEXT, None, lambda row: row["category_name"], "The category's name."),
    "Merchant": (TEXT, "name", _merchant, "The merchant, written as the charts group it."),
    "Date": (DATE, None, lambda row: row["date"], "The day of the transaction."),
    "Balance": (
        NUMBER,
        "balance",
        lambda row: row["balance"],
        "The balance after the transaction. Missing if the statement had none.",
    ),
}
_FIELD_NAMES = {name.casefold(): name for name in FIELDS}

# name -> help. Each is one value for the whole group.
VARIABLES = {
    "spend": "The group's total spend: SUM([Spend]).",
    "income": "The group's total income: SUM([Income]).",
    "net": "Income minus spend: SUM([Net]).",
    "count": "The number of transactions: COUNT([Amount]).",
    "days": "The number of calendar days the group covers.",
}

# name -> (fewest values, most values, group, signature, help).
FUNCTIONS = {
    "SUM": (1, 1, "aggregate", "SUM(x)", "Adds up x over the group's transactions."),
    "AVG": (1, 1, "aggregate", "AVG(x)", "The average of x."),
    "MEDIAN": (1, 1, "aggregate", "MEDIAN(x)", "The middle value of x."),
    "MIN": (
        1,
        MAX_ARGS,
        "aggregate",
        "MIN(x)",
        "The smallest x. MIN(a, b, …) is the smallest of its values.",
    ),
    "MAX": (
        1,
        MAX_ARGS,
        "aggregate",
        "MAX(x)",
        "The largest x. MAX(a, b, …) is the largest of its values.",
    ),
    "COUNT": (1, 1, "aggregate", "COUNT(x)", "How many transactions have a value for x."),
    "COUNTD": (1, 1, "aggregate", "COUNTD(x)", "How many different values x has."),
    "IIF": (3, 3, "logic", "IIF(test, then, else)", "then if the test is true, otherwise else."),
    "ZN": (1, 1, "logic", "ZN(x)", "x, or 0 if x is missing."),
    "IFNULL": (2, 2, "logic", "IFNULL(x, other)", "x, or other if x is missing."),
    "COALESCE": (2, MAX_ARGS, "logic", "COALESCE(a, b, …)", "The first value that is not missing."),
    "NULLIF": (2, 2, "logic", "NULLIF(a, b)", "Missing if a equals b, otherwise a."),
    "ISNULL": (1, 1, "logic", "ISNULL(x)", "True if x is missing."),
    "ABS": (1, 1, "number", "ABS(x)", "x without its minus sign."),
    "ROUND": (1, 2, "number", "ROUND(x, places)", "x rounded half up, to 0 to 6 decimal places."),
    "FLOOR": (1, 1, "number", "FLOOR(x)", "x rounded down to a whole number."),
    "CEILING": (1, 1, "number", "CEILING(x)", "x rounded up to a whole number. CEIL works too."),
    "CEIL": (1, 1, "number", "CEIL(x)", "The same as CEILING(x)."),
    "POWER": (2, 2, "number", "POWER(x, y)", "x to the power y (y from -100 to 100)."),
    "SQRT": (1, 1, "number", "SQRT(x)", "The square root of x. Missing if x is negative."),
    "SIGN": (1, 1, "number", "SIGN(x)", "-1, 0 or 1."),
    "CONTAINS": (
        2,
        2,
        "text",
        "CONTAINS(text, part)",
        "True if the text holds the part. Ignores case.",
    ),
    "STARTSWITH": (
        2,
        2,
        "text",
        "STARTSWITH(text, part)",
        "True if the text starts with the part.",
    ),
    "ENDSWITH": (2, 2, "text", "ENDSWITH(text, part)", "True if the text ends with the part."),
    "DATE": (1, 1, "date", 'DATE("YYYY-MM-DD")', "A fixed date, to compare [Date] with."),
    "YEAR": (1, 1, "date", "YEAR(date)", "The year, such as 2026."),
    "QUARTER": (1, 1, "date", "QUARTER(date)", "1 to 4."),
    "MONTH": (1, 1, "date", "MONTH(date)", "1 to 12."),
    "DAY": (1, 1, "date", "DAY(date)", "The day of the month, 1 to 31."),
    "WEEKDAY": (1, 1, "date", "WEEKDAY(date)", "1 = Monday … 7 = Sunday."),
    "DATEPART": (
        2,
        2,
        "date",
        "DATEPART('part', date)",
        "The 'year', 'quarter', 'month', 'day' or 'weekday' of a date.",
    ),
}
AGGREGATES = ("SUM", "AVG", "MEDIAN", "MIN", "MAX", "COUNT", "COUNTD")
_DATE_PARTS = {
    "year": lambda d: d.year,
    "quarter": lambda d: (d.month - 1) // 3 + 1,
    "month": lambda d: d.month,
    "day": lambda d: d.day,
    "weekday": lambda d: d.isoweekday(),
}


def language() -> dict:
    """The language as the editor lists it: names, fields, functions and keywords."""
    return {
        "variables": [{"name": name, "help": text} for name, text in VARIABLES.items()],
        "fields": [
            {"name": name, "type": kind, "help": text}
            for name, (kind, _, _, text) in FIELDS.items()
        ],
        "functions": [
            {"name": name, "signature": signature, "group": group, "help": text}
            for name, (_, _, group, signature, text) in FUNCTIONS.items()
        ],
        "keywords": list(KEYWORDS),
    }


# --- tokens -------------------------------------------------------------------------------------

_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<number>\d+(?:\.\d+)?)"
    r"|(?P<string>\"[^\"]*\"|'[^']*')"
    r"|(?P<field>\[[^\[\]]*\])"
    r"|(?P<name>[A-Za-z_][A-Za-z_0-9]*)"
    r"|(?P<symbol><=|>=|<>|!=|==|[-+*/%(),=<>])"
    r")"
)
_QUOTED = re.compile(r"(\"[^\"]*\"|'[^']*')")


def tidy(text: str) -> str:
    """The formula with each run of spaces and line breaks made one space, except inside quotes."""
    parts = _QUOTED.split(text)
    return "".join(
        part if index % 2 else re.sub(r"\s+", " ", part) for index, part in enumerate(parts)
    ).strip()


def _tokenize(text: str) -> list[tuple[str, str, int]]:
    """Split the text into (kind, value, position) tokens. Position counts from 1."""
    tokens = []
    index = 0
    while True:
        rest = text[index:]
        if not rest.strip():
            return tokens
        match = _TOKEN.match(text, index)
        if not match:
            offset = index + len(rest) - len(rest.lstrip())
            char = text[offset]
            if char in "\"'":
                raise FormulaError(f"The text at position {offset + 1} has no closing {char}.")
            if char == "[":
                raise FormulaError(f"The field name at position {offset + 1} has no closing ].")
            raise FormulaError(f"Unexpected character {char!r} at position {offset + 1}.")
        kind = match.lastgroup
        value = match.group(kind)
        position = match.start(kind) + 1
        if kind == "number" and len(value.replace(".", "")) > MAX_DIGITS:
            raise FormulaError(
                f"A number is longer than {MAX_DIGITS} digits at position {position}."
            )
        if kind in ("string", "field"):
            value = value[1:-1]
        if kind == "string" and len(value) > MAX_STRING:
            raise FormulaError(
                f"A text is longer than {MAX_STRING} characters at position {position}."
            )
        tokens.append((kind, value, position))
        if len(tokens) > MAX_TOKENS:
            raise FormulaError(f"The formula is longer than {MAX_TOKENS} parts.")
        index = match.end()


# --- the parser ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Node:
    """One part of the parsed formula. `value` depends on the kind; `args` are its parts."""

    kind: str
    position: int
    value: object = None
    args: tuple = ()


_COMPARISONS = ("=", "==", "<>", "!=", "<", "<=", ">", ">=")
_SAME_AS = {"==": "=", "!=": "<>"}


class _Parser:
    """expr    := or
    or      := and ("OR" and)*
    and     := not ("AND" not)*
    not     := "NOT" not | compare
    compare := sum [(= | <> | < | <= | > | >=) sum | ["NOT"] "IN" "(" sum ("," sum)* ")"]
    sum     := product (("+" | "-") product)*
    product := unary (("*" | "/" | "%") unary)*
    unary   := "-" unary | primary
    primary := NUMBER | TEXT | FIELD | NAME | NAME "(" expr ("," expr)* ")" | "(" expr ")"
             | TRUE | FALSE | NULL | if | case
    if      := "IF" expr "THEN" expr ("ELSEIF" expr "THEN" expr)* ["ELSE" expr] "END"
    case    := "CASE" [expr] ("WHEN" expr "THEN" expr)+ ["ELSE" expr] "END"

    CASE x WHEN v ... becomes CASE WHEN x = v ..., and IIF(c, a, b) becomes an IF.
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    def peek(self, ahead: int = 0):
        index = self.index + ahead
        return self.tokens[index] if index < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.index += 1
        return token

    def symbol(self, *symbols: str, ahead: int = 0):
        """The next token if it is one of these symbols, else None."""
        token = self.peek(ahead)
        return token if token and token[0] == "symbol" and token[1] in symbols else None

    def keyword(self, *words: str, ahead: int = 0):
        """The next token if it is one of these keywords, else None."""
        token = self.peek(ahead)
        return token if token and token[0] == "name" and token[1].upper() in words else None

    def expect(self, symbol: str):
        token = self.take()
        if token is None or token[0] != "symbol" or token[1] != symbol:
            where = f"at position {token[2]}" if token else "at the end"
            raise FormulaError(f"Expected {symbol!r} {where}.")

    def expect_keyword(self, word: str, opener: str, position: int):
        token = self.take()
        if token is None or token[0] != "name" or token[1].upper() != word:
            raise FormulaError(f"Expected {word} for the {opener} at position {position}.")

    def parse(self):
        if not self.tokens:
            raise FormulaError("The formula is empty.")
        node = self.expression()
        extra = self.peek()
        if extra is not None:
            raise FormulaError(f"Unexpected {extra[1]!r} at position {extra[2]}.")
        return node

    def nested(self, parse):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError(f"The formula nests brackets deeper than {MAX_DEPTH} levels.")
        try:
            return parse()
        finally:
            self.depth -= 1

    def expression(self):
        node = self.conjunction()
        while token := self.keyword("OR"):
            self.take()
            node = _Node("or", token[2], args=(node, self.conjunction()))
        return node

    def conjunction(self):
        node = self.negation()
        while token := self.keyword("AND"):
            self.take()
            node = _Node("and", token[2], args=(node, self.negation()))
        return node

    def negation(self):
        if token := self.keyword("NOT"):
            self.take()
            return _Node("not", token[2], args=(self.nested(self.negation),))
        return self.comparison()

    def comparison(self):
        node = self.sum()
        if token := self.symbol(*_COMPARISONS):
            self.take()
            symbol = _SAME_AS.get(token[1], token[1])
            node = _Node("compare", token[2], symbol, (node, self.sum()))
        elif self.keyword("IN") or (self.keyword("NOT") and self.keyword("IN", ahead=1)):
            token = self.take()
            negated = token[1].upper() == "NOT"
            if negated:
                self.take()
            node = _Node("in", token[2], negated, (node, *self.nested(self.items)))
        if token := self.symbol(*_COMPARISONS) or self.keyword("IN"):
            raise FormulaError(
                f"Comparisons cannot be chained, at position {token[2]}. Join them with AND."
            )
        return node

    def items(self):
        self.expect("(")
        items = [self.sum()]
        while self.symbol(","):
            self.take()
            items.append(self.sum())
            if len(items) > MAX_IN_ITEMS:
                raise FormulaError(f"IN (...) takes at most {MAX_IN_ITEMS} values.")
        self.expect(")")
        return items

    def sum(self):
        node = self.product()
        while token := self.symbol("+", "-"):
            self.take()
            node = _Node("op", token[2], token[1], (node, self.product()))
        return node

    def product(self):
        node = self.unary()
        while token := self.symbol("*", "/", "%"):
            self.take()
            node = _Node("op", token[2], token[1], (node, self.unary()))
        return node

    def unary(self):
        if token := self.symbol("-"):
            self.take()
            return _Node("neg", token[2], args=(self.nested(self.unary),))
        return self.primary()

    def primary(self):
        token = self.take()
        if token is None:
            raise FormulaError("The formula ends too soon.")
        kind, value, position = token
        if kind == "number":
            return _Node("number", position, Decimal(value))
        if kind == "string":
            return _Node("text", position, value)
        if kind == "field":
            return _Node("field", position, _field_name(value, position))
        if kind == "name":
            return self.word(value, position)
        if value == "(":
            node = self.nested(self.expression)
            self.expect(")")
            return node
        raise FormulaError(f"Unexpected {value!r} at position {position}.")

    def word(self, value: str, position: int):
        upper = value.upper()
        if upper in ("TRUE", "FALSE"):
            return _Node("bool", position, upper == "TRUE")
        if upper == "NULL":
            return _Node("null", position)
        if upper == "IF":
            return self.nested(lambda: self.conditional(position))
        if upper == "CASE":
            return self.nested(lambda: self.case(position))
        if upper in KEYWORDS:
            raise FormulaError(f"Unexpected {value!r} at position {position}.")
        if self.symbol("("):
            if upper not in FUNCTIONS:
                raise FormulaError(
                    f"Unknown function {value!r} at position {position}. "
                    f"Use {', '.join(FUNCTIONS)}."
                )
            self.take()
            args = self.nested(self.arguments)
            low, high = FUNCTIONS[upper][:2]
            if not low <= len(args) <= high:
                raise FormulaError(f"{upper}() takes {_how_many(low, high)}, not {len(args)}.")
            if upper == "IIF":
                return _Node("if", position, "IIF", tuple(args))
            return _Node("call", position, upper, tuple(args))
        if value.lower() in VARIABLES:
            return _Node("total", position, value.lower())
        raise FormulaError(
            f"Unknown name {value!r} at position {position}. "
            f"Use {', '.join(VARIABLES)}, or a field in brackets such as [Amount]."
        )

    def arguments(self):
        args = [self.expression()]
        while self.symbol(","):
            self.take()
            args.append(self.expression())
            if len(args) > MAX_ARGS:
                raise FormulaError(f"A function takes at most {MAX_ARGS} values.")
        self.expect(")")
        return args

    def conditional(self, position: int):
        parts = []
        while True:
            parts.append(self.expression())
            self.expect_keyword("THEN", "IF", position)
            parts.append(self.expression())
            if not self.keyword("ELSEIF"):
                break
            self.take()
        return _Node("if", position, "IF", (*parts, self.otherwise("IF", position)))

    def case(self, position: int):
        subject = None if self.keyword("WHEN") else self.expression()
        parts = []
        while token := self.keyword("WHEN"):
            self.take()
            test = self.expression()
            if subject is not None:
                test = _Node("compare", token[2], "=", (subject, test))
            self.expect_keyword("THEN", "CASE", position)
            parts += [test, self.expression()]
        if not parts:
            raise FormulaError(f"The CASE at position {position} needs at least one WHEN.")
        return _Node("if", position, "CASE", (*parts, self.otherwise("CASE", position)))

    def otherwise(self, opener: str, position: int):
        """The ELSE part and the END of an IF or CASE. With no ELSE the answer is NULL."""
        node = _Node("null", position)
        if self.keyword("ELSE"):
            self.take()
            node = self.expression()
        self.expect_keyword("END", opener, position)
        return node


def _field_name(value: str, position: int) -> str:
    name = _FIELD_NAMES.get(value.strip().casefold())
    if name is None:
        fields = ", ".join(f"[{field}]" for field in FIELDS)
        raise FormulaError(f"Unknown field [{value}] at position {position}. Use {fields}.")
    return name


def _how_many(low: int, high: int) -> str:
    if low == high:
        return f"{low} value" + ("s" if low > 1 else "")
    if high == low + 1:
        return f"{low} or {high} values"
    return f"{low} to {high} values"


# --- checking and building ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Part:
    """A checked part of the formula and the function that works it out.

    `run` takes a row for a per-transaction part, a _Group for a total, and anything for a
    constant. It returns a Decimal, str, date or bool, or None for a missing value.
    """

    type: str
    level: int
    run: Callable
    node: _Node


def _lift(fn, runs):
    """A run that gives None if any value is missing, else fn(*values)."""
    if len(runs) == 1:
        (only,) = runs

        def run(context):
            value = only(context)
            return None if value is None else fn(value)

    elif len(runs) == 2:
        first, second = runs

        def run(context):
            a = first(context)
            if a is None:
                return None
            b = second(context)
            return None if b is None else fn(a, b)

    else:

        def run(context):
            values = [part(context) for part in runs]
            return None if any(value is None for value in values) else fn(*values)

    return run


def _divide(a, b):
    return None if b == 0 else a / b


def _remainder(a, b):
    return None if b == 0 else a % b


_ARITHMETIC = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": _divide,
    "%": _remainder,
}
_ORDER = {
    "=": operator.eq,
    "<>": operator.ne,
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
}


def _median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _distinct(value):
    return value.casefold() if isinstance(value, str) else value


# Each turns the non-missing values of a group into one number. The same as engine.aggregate.
_REDUCERS = {
    "SUM": lambda values: sum(values, Decimal(0)),
    "AVG": lambda values: sum(values, Decimal(0)) / len(values) if values else None,
    "MEDIAN": lambda values: _median(values) if values else None,
    "MIN": lambda values: min(values) if values else None,
    "MAX": lambda values: max(values) if values else None,
    "COUNT": lambda values: Decimal(len(values)),
    "COUNTD": lambda values: Decimal(len({_distinct(value) for value in values})),
}


def _is_aggregate(node: _Node) -> bool:
    return node.kind == "total" or (
        node.kind == "call" and node.value in AGGREGATES and len(node.args) == 1
    )


def _find(node: _Node, test) -> _Node | None:
    """The first part of `node`, reading left to right, that passes `test`."""
    if test(node):
        return node
    for arg in node.args:
        if found := _find(arg, test):
            return found
    return None


def _per_transaction(node: _Node) -> FormulaError:
    field = _find(node, lambda part: part.kind == "field")
    return FormulaError(
        f"[{field.value}] is a value for each transaction, at position {field.position}. "
        "Put it inside SUM(), AVG(), COUNT()… to use it with totals."
    )


def _power(x, y):
    if abs(y) > MAX_POWER:
        return None
    try:
        return x**y
    except ArithmeticError:  # 0 to a negative power, or a root of a negative number
        return None


def _round(places: int):
    step = Decimal(1).scaleb(-places)
    return lambda x: x.quantize(step, rounding=ROUND_HALF_UP)


_NUMBER_FUNCTIONS = {
    "ABS": abs,
    "FLOOR": lambda x: x.to_integral_value(rounding=ROUND_FLOOR),
    "CEILING": lambda x: x.to_integral_value(rounding=ROUND_CEILING),
    "CEIL": lambda x: x.to_integral_value(rounding=ROUND_CEILING),
    "SQRT": lambda x: None if x < 0 else x.sqrt(),
    "SIGN": lambda x: Decimal((x > 0) - (x < 0)),
}
_TEXT_FUNCTIONS = {
    "CONTAINS": lambda text, part: part.casefold() in text.casefold(),
    "STARTSWITH": lambda text, part: text.casefold().startswith(part.casefold()),
    "ENDSWITH": lambda text, part: text.casefold().endswith(part.casefold()),
}
_DATE_FUNCTIONS = {"YEAR", "QUARTER", "MONTH", "DAY", "WEEKDAY"}
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class _Builder:
    """Checks each part of the tree and builds the function that works it out."""

    def __init__(self):
        self.fields: set[str] = set()  # the optional row fields the formula reads
        self.uses_days = False

    def build(self, node: _Node) -> _Part:
        return getattr(self, f"build_{node.kind}")(node)

    # --- helpers

    def level(self, parts) -> int:
        levels = {part.level for part in parts}
        if ROW in levels and TOTAL in levels:
            raise _per_transaction(next(part for part in parts if part.level == ROW).node)
        return max(levels, default=CONST)

    def need(self, part: _Part, wanted: tuple, what: str):
        if part.type != NULL and part.type not in wanted:
            words = " or ".join(_TYPE_WORDS[kind] for kind in wanted)
            raise FormulaError(
                f"{what} needs {words}, not {_TYPE_WORDS[part.type]}, "
                f"at position {part.node.position}."
            )

    def same_type(self, parts, what: str, position: int) -> str:
        """The one type all the parts share (NULL fits any)."""
        kinds = list(dict.fromkeys(part.type for part in parts if part.type != NULL))
        if len(kinds) > 1:
            raise FormulaError(
                f"{what} mixes {_TYPE_WORDS[kinds[0]]} and {_TYPE_WORDS[kinds[1]]} "
                f"at position {position}."
            )
        return kinds[0] if kinds else NULL

    def fixed(self, part: _Part, what: str):
        """The value of a part that must not depend on the transactions."""
        if part.level != CONST:
            raise FormulaError(f"{what} must be a fixed value, at position {part.node.position}.")
        try:
            return part.run(None)
        except ArithmeticError:
            raise FormulaError(f"{what} has no value, at position {part.node.position}.") from None

    def made(self, kind: str, parts, run, node: _Node) -> _Part:
        return _Part(kind, self.level(parts), run, node)

    # --- values and names

    def constant(self, kind: str, value, node: _Node) -> _Part:
        return _Part(kind, CONST, lambda _: value, node)

    def build_number(self, node):
        return self.constant(NUMBER, node.value, node)

    def build_text(self, node):
        return self.constant(TEXT, node.value, node)

    def build_bool(self, node):
        return self.constant(BOOL, node.value, node)

    def build_null(self, node):
        return self.constant(NULL, None, node)

    def build_field(self, node):
        kind, needs, reader, _ = FIELDS[node.value]
        if needs:
            self.fields.add(needs)
        return _Part(kind, ROW, reader, node)

    def build_total(self, node):
        name = node.value
        if name == "days":
            self.uses_days = True
            return _Part(NUMBER, TOTAL, lambda group: group.days(), node)
        return _Part(NUMBER, TOTAL, lambda group: group.totals[name], node)

    # --- operators

    def build_neg(self, node):
        inner = self.build(node.args[0])
        self.need(inner, (NUMBER,), "A minus sign")
        return self.made(NUMBER, [inner], _lift(operator.neg, [inner.run]), node)

    def build_op(self, node):
        left, right = (self.build(arg) for arg in node.args)
        for part in (left, right):
            self.need(part, (NUMBER,), node.value)
        run = _lift(_ARITHMETIC[node.value], [left.run, right.run])
        return self.made(NUMBER, [left, right], run, node)

    def build_compare(self, node):
        left, right = (self.build(arg) for arg in node.args)
        kinds = [part.type for part in (left, right) if part.type != NULL]
        if len(kinds) == 2 and kinds[0] != kinds[1]:
            hint = ' Write a date as DATE("YYYY-MM-DD").' if DATE in kinds else ""
            raise FormulaError(
                f"Cannot compare {_TYPE_WORDS[kinds[0]]} with {_TYPE_WORDS[kinds[1]]} "
                f"at position {node.position}.{hint}"
            )
        if BOOL in kinds and node.value not in ("=", "<>"):
            raise FormulaError(f"Cannot order true/false values at position {node.position}.")
        test = _ORDER[node.value]
        if TEXT in kinds:
            run = _lift(lambda a, b: test(a.casefold(), b.casefold()), [left.run, right.run])
        else:
            run = _lift(test, [left.run, right.run])
        return self.made(BOOL, [left, right], run, node)

    def build_in(self, node):
        subject = self.build(node.args[0])
        items = [self.build(arg) for arg in node.args[1:]]
        self.same_type([subject, *items], "IN (...)", node.position)
        values = {_distinct(self.fixed(item, "A value in IN (...)")) for item in items}
        values.discard(None)
        read, negated = subject.run, node.value

        def run(context):
            value = read(context)
            return None if value is None else (_distinct(value) in values) != negated

        return _Part(BOOL, subject.level, run, node)

    def build_not(self, node):
        inner = self.build(node.args[0])
        self.need(inner, (BOOL,), "NOT")
        return self.made(BOOL, [inner], _lift(operator.not_, [inner.run]), node)

    def build_and(self, node):
        left, right = self.logic(node, "AND")
        first, second = left.run, right.run

        def run(context):  # SQL's three-valued logic: FALSE AND NULL is FALSE
            a = first(context)
            if a is False:
                return False
            b = second(context)
            if b is False:
                return False
            return None if a is None or b is None else True

        return self.made(BOOL, [left, right], run, node)

    def build_or(self, node):
        left, right = self.logic(node, "OR")
        first, second = left.run, right.run

        def run(context):  # TRUE OR NULL is TRUE
            a = first(context)
            if a is True:
                return True
            b = second(context)
            if b is True:
                return True
            return None if a is None or b is None else False

        return self.made(BOOL, [left, right], run, node)

    def logic(self, node, word: str):
        parts = [self.build(arg) for arg in node.args]
        for part in parts:
            self.need(part, (BOOL,), word)
        return parts

    def build_if(self, node):
        label = node.value
        parts = [self.build(arg) for arg in node.args]
        tests, answers = parts[0:-1:2], [*parts[1:-1:2], parts[-1]]
        for test in tests:
            if test.type not in (BOOL, NULL):
                raise FormulaError(
                    f"{label} needs a true/false condition at position {test.node.position}."
                )
        kind = self.same_type(answers, f"This {label}", node.position)
        pairs = [(test.run, answer.run) for test, answer in zip(tests, answers, strict=False)]
        otherwise = answers[-1].run

        def run(context):
            for test, answer in pairs:
                if test(context) is True:
                    return answer(context)
            return otherwise(context)

        return self.made(kind, parts, run, node)

    # --- functions

    def build_call(self, node):
        name = node.value
        if name in AGGREGATES and len(node.args) == 1:
            return self.aggregate(node)
        parts = [self.build(arg) for arg in node.args]
        runs = [part.run for part in parts]
        what = f"{name}()"

        if name in ("MIN", "MAX"):
            for part in parts:
                self.need(part, (NUMBER,), what)
            return self.made(NUMBER, parts, _lift(min if name == "MIN" else max, runs), node)
        if name in _NUMBER_FUNCTIONS:
            self.need(parts[0], (NUMBER,), what)
            return self.made(NUMBER, parts, _lift(_NUMBER_FUNCTIONS[name], runs), node)
        if name == "ROUND":
            self.need(parts[0], (NUMBER,), what)
            places = 0
            if len(parts) == 2:
                self.need(parts[1], (NUMBER,), what)
                places = self.fixed(parts[1], "The places of ROUND()")
                if places is None or places != int(places) or not 0 <= places <= MAX_PLACES:
                    raise FormulaError(
                        f"ROUND() takes 0 to {MAX_PLACES} decimal places, "
                        f"at position {parts[1].node.position}."
                    )
            return self.made(NUMBER, parts, _lift(_round(int(places)), runs[:1]), node)
        if name == "POWER":
            for part in parts:
                self.need(part, (NUMBER,), what)
            if parts[1].level == CONST:
                power = self.fixed(parts[1], "The power of POWER()")
                if power is not None and abs(power) > MAX_POWER:
                    raise FormulaError(
                        f"POWER() takes a power from -{MAX_POWER} to {MAX_POWER}, "
                        f"at position {parts[1].node.position}."
                    )
            return self.made(NUMBER, parts, _lift(_power, runs), node)
        if name == "ZN":
            self.need(parts[0], (NUMBER,), what)
            (read,) = runs
            return self.made(
                NUMBER, parts, lambda c: Decimal(0) if (v := read(c)) is None else v, node
            )
        if name in ("IFNULL", "COALESCE"):
            kind = self.same_type(parts, what, node.position)

            def first_known(context):
                for read in runs:
                    if (value := read(context)) is not None:
                        return value
                return None

            return self.made(kind, parts, first_known, node)
        if name == "NULLIF":
            kind = self.same_type(parts, what, node.position)
            first, second = runs

            def null_if(context):
                a = first(context)
                if a is None:
                    return None
                b = second(context)
                return None if b is not None and _distinct(a) == _distinct(b) else a

            return self.made(kind, parts, null_if, node)
        if name == "ISNULL":
            (read,) = runs
            return self.made(BOOL, parts, lambda c: read(c) is None, node)
        if name in _TEXT_FUNCTIONS:
            for part in parts:
                self.need(part, (TEXT,), what)
            return self.made(BOOL, parts, _lift(_TEXT_FUNCTIONS[name], runs), node)
        if name == "DATE":
            return self.date_literal(parts[0])
        if name in _DATE_FUNCTIONS:
            self.need(parts[0], (DATE,), what)
            reader = _DATE_PARTS[name.lower()]
            return self.made(NUMBER, parts, _lift(lambda d: Decimal(reader(d)), runs), node)
        # DATEPART
        self.need(parts[0], (TEXT,), what)
        self.need(parts[1], (DATE,), what)
        part = self.fixed(parts[0], "The part of DATEPART()")
        reader = _DATE_PARTS.get((part or "").lower())
        if reader is None:
            raise FormulaError(
                f"DATEPART() takes {', '.join(repr(p) for p in _DATE_PARTS)}, "
                f"at position {parts[0].node.position}."
            )
        return self.made(NUMBER, parts, _lift(lambda d: Decimal(reader(d)), runs[1:]), node)

    def date_literal(self, part: _Part) -> _Part:
        position = part.node.position
        text = self.fixed(part, "DATE()") if part.type == TEXT else None
        if not isinstance(text, str):
            raise FormulaError(
                f'DATE() takes a date written as text, such as DATE("2026-01-31"), '
                f"at position {position}."
            )
        try:
            if not _ISO_DATE.fullmatch(text):
                raise ValueError
            day = date.fromisoformat(text)
        except ValueError:
            raise FormulaError(
                f'Not a date: "{text}" at position {position}. Use DATE("YYYY-MM-DD").'
            ) from None
        return self.constant(DATE, day, part.node)

    def aggregate(self, node):
        name = node.value
        part = self.build(node.args[0])
        if part.level == TOTAL:
            inner = _find(node.args[0], _is_aggregate)
            raise FormulaError(
                f"{name}() cannot contain another aggregate or a total, "
                f"at position {inner.position}."
            )
        if name not in ("COUNT", "COUNTD"):
            self.need(part, (NUMBER,), f"{name}()")
        read, reduce = part.run, _REDUCERS[name]

        def run(group):
            return reduce([value for row in group.rows if (value := read(row)) is not None])

        return _Part(NUMBER, TOTAL, run, node)


# --- running a formula ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Compiled:
    """A checked formula, ready to run on groups of rows."""

    run: Callable  # _Group -> Decimal | None
    uses_days: bool
    fields: frozenset  # optional row fields it reads: "name" (for [Merchant]), "balance"


class _Group:
    """One group of rows as a formula sees it. Totals and days are worked out only if asked."""

    __slots__ = ("rows", "_days", "_totals")

    def __init__(self, rows: list[dict], days: Callable[[], int] | None):
        self.rows = rows
        self._days = days
        self._totals = None

    @property
    def totals(self) -> dict:
        if self._totals is None:
            self._totals = totals(self.rows)
        return self._totals

    def days(self) -> Decimal:
        if self._days is not None:
            return Decimal(self._days())
        # No span given: the days from the first transaction to the last.
        dates = [row["date"] for row in self.rows]
        return Decimal((max(dates) - min(dates)).days + 1) if dates else Decimal(0)


def _compile(text: str) -> Compiled:
    builder = _Builder()
    part = builder.build(_Parser(_tokenize(text)).parse())
    if part.level == ROW:
        raise _per_transaction(part.node)
    if part.type not in (NUMBER, NULL):
        raise FormulaError(
            f"The formula must give a number, not {_TYPE_WORDS[part.type]}. To count matches, "
            "use SUM(IIF(…, 1, 0)) or COUNT(IF … THEN 1 END)."
        )
    return Compiled(part.run, builder.uses_days, frozenset(builder.fields))


# Compiled formulas for the run in progress (see parse_once), or None outside one.
_parsed: ContextVar[dict | None] = ContextVar("parsed_formulas", default=None)


@contextmanager
def parse_once():
    """Inside this block each formula is parsed once, however many groups it is worked out for.

    The trees are dropped when the block ends. A process-wide cache would keep users' formulas
    in memory after their request, and they are stored encrypted for a reason.
    """
    token = _parsed.set({})
    try:
        yield
    finally:
        _parsed.reset(token)


def compile_expression(text: str) -> Compiled:
    """The checked formula for `text`. Raises FormulaError."""
    if not isinstance(text, str):
        raise FormulaError("The formula must be text.")
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"The formula is longer than {MAX_LENGTH} characters.")
    cache = _parsed.get()
    if cache is not None and text in cache:
        return cache[text]
    compiled = _compile(text)
    if cache is not None:
        cache[text] = compiled
    return compiled


def fields_used(text: str) -> frozenset:
    """The optional row fields a valid formula reads, so the caller can decrypt them."""
    return compile_expression(text).fields


def totals(rows: list[dict]) -> dict:
    """The values the totals stand for, over one group of rows (all but `days`)."""
    spend = income = Decimal(0)
    for row in rows:
        if row["txn_type"] == "debit":
            spend += row["amount"]
        else:
            income += row["amount"]
    return {"spend": spend, "income": income, "net": income - spend, "count": Decimal(len(rows))}


def days_in(start: date, end: date, weekdays=None, months=None) -> int:
    """The calendar days from start to end, both included, that fall on one of `weekdays`
    (0 = Monday, as date.weekday()) and in one of `months` (1 to 12). None means any."""
    if end < start:
        return 0
    if not weekdays and not months:
        return (end - start).days + 1
    count, day = 0, start
    while day <= end:
        if (not weekdays or day.weekday() in weekdays) and (not months or day.month in months):
            count += 1
        day += timedelta(days=1)
    return count


def evaluate_rows(text: str, rows: list[dict], days: Callable[[], int] | None = None):
    """The formula's value for one group of rows, or None if it has no answer (dividing by zero,
    or a result too large to show). `days` gives the calendar days the group covers, and is
    called only if the formula uses `days`. Raises FormulaError if the text is not a valid
    formula."""
    compiled = compile_expression(text)
    try:
        result = compiled.run(_Group(rows, days))
    except ArithmeticError:  # a Decimal that overflowed, or an operation with no answer
        return None
    if result is None or abs(result) > MAX_RESULT:
        return None
    return result
