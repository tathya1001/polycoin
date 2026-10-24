"""Calculated fields: a small, safe expression language over a group's totals.

A panel can show a number it computes itself, such as a savings rate:

    (income - spend) / income * 100

The names are the group's totals (a month's, a category's...): `spend`, `income`, `net` and
`count`. The language has numbers, + - * /, brackets, and the functions abs(x), min(a, b) and
max(a, b). Nothing else: no assignment, no attributes, no strings, no calls to anything defined
elsewhere.

The text is never passed to eval() or exec(). It is split into tokens, parsed into a small tree
by a recursive-descent parser (the classic way to read arithmetic), and the tree is evaluated
with Decimal numbers. The limits below bound the work any one expression can cost: a request
cannot make the server spin by sending a long or deeply nested formula.
"""

import re
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal

FORMULA = "formula"  # the y.measure value of a panel that shows a calculated field
VARIABLES = ("spend", "income", "net", "count")
FUNCTIONS = {"abs": 1, "min": 2, "max": 2}  # name -> number of arguments
RESULT_FORMS = ("number", "percent", "money")

MAX_LENGTH = 200  # characters
MAX_TOKENS = 80
MAX_DEPTH = 8  # nested brackets, function calls and minus signs
MAX_DIGITS = 12  # in one number
# A bigger result cannot be stored to the cent in a Decimal (28 digits) and means a mistake.
MAX_RESULT = Decimal("1e15")


class FormulaError(ValueError):
    """The formula cannot be used. The message says what is wrong and where."""


_TOKEN = re.compile(
    r"""\s*(?:
        (?P<number>\d+(?:\.\d+)?)
      | (?P<name>[A-Za-z_][A-Za-z_0-9]*)
      | (?P<symbol>[-+*/(),])
    )""",
    re.VERBOSE,
)


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
            raise FormulaError(f"Unexpected character {text[offset]!r} at position {offset + 1}.")
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "number" and len(value.replace(".", "")) > MAX_DIGITS:
            raise FormulaError(
                f"A number is longer than {MAX_DIGITS} digits at position {match.start(kind) + 1}."
            )
        tokens.append((kind, value, match.start(kind) + 1))
        if len(tokens) > MAX_TOKENS:
            raise FormulaError(f"The formula is longer than {MAX_TOKENS} parts.")
        index = match.end()


class _Parser:
    """expr   := term (("+" | "-") term)*
    term   := factor (("*" | "/") factor)*
    factor := "-" factor | NUMBER | NAME | NAME "(" expr ("," expr)* ")" | "(" expr ")"

    The tree is nested tuples: ("number", Decimal), ("name", str), ("neg", node),
    ("op", symbol, left, right), ("call", name, [args]).
    """

    def __init__(self, tokens):
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.index] if self.index < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.index += 1
        return token

    def expect(self, symbol: str):
        token = self.take()
        if token is None or token[1] != symbol:
            where = f"at position {token[2]}" if token else "at the end"
            raise FormulaError(f"Expected {symbol!r} {where}.")

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
        node = self.term()
        while (token := self.peek()) and token[1] in "+-" and token[0] == "symbol":
            self.take()
            node = ("op", token[1], node, self.term())
        return node

    def term(self):
        node = self.factor()
        while (token := self.peek()) and token[1] in "*/" and token[0] == "symbol":
            self.take()
            node = ("op", token[1], node, self.factor())
        return node

    def factor(self):
        token = self.take()
        if token is None:
            raise FormulaError("The formula ends too soon.")
        kind, value, position = token
        if kind == "number":
            return ("number", Decimal(value))
        if kind == "name":
            return self.name(value, position)
        if value == "-":
            return ("neg", self.nested(self.factor))
        if value == "(":
            node = self.nested(self.expression)
            self.expect(")")
            return node
        raise FormulaError(f"Unexpected {value!r} at position {position}.")

    def name(self, value: str, position: int):
        following = self.peek()
        if following and following[1] == "(":
            if value not in FUNCTIONS:
                raise FormulaError(
                    f"Unknown function {value!r} at position {position}. Use {_listed(FUNCTIONS)}."
                )
            self.take()
            args = self.nested(self.arguments)
            if len(args) != FUNCTIONS[value]:
                raise FormulaError(f"{value}() takes {FUNCTIONS[value]} value(s), not {len(args)}.")
            return ("call", value, args)
        if value not in VARIABLES:
            raise FormulaError(
                f"Unknown name {value!r} at position {position}. Use {_listed(VARIABLES)}."
            )
        return ("name", value)

    def arguments(self):
        args = [self.expression()]
        while (token := self.peek()) and token[1] == ",":
            self.take()
            args.append(self.expression())
        self.expect(")")
        return args


def _listed(names) -> str:
    return ", ".join(names)


# Parsed trees for the run in progress (see parse_once), or None outside one.
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


def compile_expression(text: str):
    """The parsed tree for `text`. Raises FormulaError."""
    if not isinstance(text, str):
        raise FormulaError("The formula must be text.")
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"The formula is longer than {MAX_LENGTH} characters.")
    cache = _parsed.get()
    if cache is not None and text in cache:
        return cache[text]
    tree = _Parser(_tokenize(text)).parse()
    if cache is not None:
        cache[text] = tree
    return tree


def _evaluate(node, values: dict) -> Decimal | None:
    """The node's value, or None where the sum has no answer (dividing by zero)."""
    kind = node[0]
    if kind == "number":
        return node[1]
    if kind == "name":
        return values[node[1]]
    if kind == "neg":
        inner = _evaluate(node[1], values)
        return None if inner is None else -inner
    if kind == "call":
        args = [_evaluate(arg, values) for arg in node[2]]
        if any(arg is None for arg in args):
            return None
        return {"abs": lambda: abs(args[0]), "min": lambda: min(args), "max": lambda: max(args)}[
            node[1]
        ]()
    _, symbol, left_node, right_node = node
    left, right = _evaluate(left_node, values), _evaluate(right_node, values)
    if left is None or right is None:
        return None
    if symbol == "+":
        return left + right
    if symbol == "-":
        return left - right
    if symbol == "*":
        return left * right
    if right == 0:
        return None
    return left / right


def totals(rows: list[dict]) -> dict:
    """The values the names stand for, over one group of rows."""
    spend = income = Decimal(0)
    for row in rows:
        if row["txn_type"] == "debit":
            spend += row["amount"]
        else:
            income += row["amount"]
    return {"spend": spend, "income": income, "net": income - spend, "count": Decimal(len(rows))}


def evaluate_rows(text: str, rows: list[dict]) -> Decimal | None:
    """The formula's value for one group of rows, or None if it has no answer (dividing by zero,
    or a result too large to show). Raises FormulaError if the text is not a valid formula."""
    try:
        result = _evaluate(compile_expression(text), totals(rows))
    except ArithmeticError:  # a Decimal that overflowed
        return None
    if result is None or abs(result) > MAX_RESULT:
        return None
    return result
