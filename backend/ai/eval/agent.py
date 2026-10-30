"""The panel builder's evaluation set and how a case is scored.

agent_cases.json holds fictional requests. Each turn has the reply a correct model gives
("golden") and what the finished panel must show ("expect"). A field in "expect" is a value or a
list of acceptable values; "categories" is the exact set of category names. Scoring looks at the
finished panel, not the model's raw reply, so two replies that build the same panel score the
same, and the server's own fixes count.

Used by ai/test_agent_eval.py (CI: golden replies through the real workflow) and
ai/test_agent_llm_eval.py (opt-in: a real model on the user's machine).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from categories.models import Category
from transactions.tests import make_txn

from ..agent import service
from ..agent.errors import AgentError
from ..agent.schema import parse_intent

CASES_FILE = Path(__file__).with_name("agent_cases.json")
FIELDS = (
    "kind", "chart", "measure", "also_measures", "agg", "x", "granularity", "color", "rows", "period",
    "categories", "merchant", "txn_type", "limit", "sort", "compare", "calc",
)  # fmt: skip

# Every name is made up. (merchant, category, days ago of each payment)
SPENDING = [
    ("Tastybites Cafe", "Food", (1, 9, 20, 41, 70, 370)),
    ("Fitzone Gym", "Health", (3, 33, 63, 365)),
    ("Greenleaf Grocers", "Groceries", (2, 12, 26, 47, 90, 380)),
    ("Cobalt Cabs", "Transport", (4, 15, 38, 66)),
    ("Maple Street Homes", "Rent", (5, 35, 65, 368)),
    ("Riverstone Books", "Shopping", (18, 120)),
]
SALARY = ("Acme Payroll", "Salary", (6, 36, 66, 96, 371))


def load_cases() -> list[dict]:
    return json.loads(CASES_FILE.read_text())


def seed(user, today: date) -> None:
    """A few months of fictional spending and salary, plus a year-ago month for comparisons."""
    categories = {category.name: category for category in Category.objects.filter(user=user)}
    rows = [(name, category, days, "debit") for name, category, days in SPENDING]
    rows.append((*SALARY, "credit"))
    for name, category, days_ago, kind in rows:
        for n, days in enumerate(days_ago):
            make_txn(
                user,
                name=name,
                description=f"UPI/{name.upper()}/{n}",
                date=today - timedelta(days=days),
                txn_type=kind,
                amount=Decimal("5000.00") if kind == "credit" else Decimal(f"{12 + 7 * n}.50"),
                balance=Decimal(f"{9000 - 40 * days}.00"),
                category=categories[category],
            )


def golden_reply(fields: dict) -> str:
    return json.dumps({"kind": "panel", **fields})


def observed(outcome: dict | None, names: dict) -> dict:
    """What a turn's outcome shows, in the fields "expect" uses. `names` maps category ids."""
    if not outcome or outcome["kind"] != "preview":
        return {"kind": (outcome or {}).get("kind", "none")}
    spec = outcome["config"]
    filters = spec["filters"]
    return {
        "kind": "panel",
        "chart": spec["chart"],
        "measure": spec["y"]["measure"],
        "also_measures": [item["measure"] for item in spec.get("also", ())],
        "agg": spec["y"]["agg"],
        "x": spec.get("x", {}).get("field"),
        "granularity": spec.get("x", {}).get("granularity"),
        "color": spec.get("color", {}).get("field"),
        "rows": spec.get("rows", {}).get("field"),
        "period": filters["date"]["preset"],
        "categories": sorted(names.get(pk, pk) for pk in filters["categories"]),
        "merchant": filters["merchant_contains"],
        "txn_type": filters["type"],
        "limit": spec["limit"],
        "sort": spec["sort"],
        "compare": spec.get("kpi", {}).get("compare"),
        "calc": spec.get("calc", {}).get("type"),
    }


def score(expect: dict, seen: dict) -> dict[str, bool]:
    """Field by field: does the panel show what was expected? "kind" is always checked."""
    wanted = {"kind": "panel", **expect}
    if wanted["kind"] != "panel" or seen["kind"] != "panel":
        return {"kind": seen["kind"] == wanted["kind"]}
    result = {}
    for name, value in wanted.items():
        if name == "categories":
            result[name] = sorted(value) == seen[name]
        elif name == "also_measures":
            result[name] = value == seen[name]
        else:
            result[name] = seen[name] in (value if isinstance(value, list) else [value])
    return result


@dataclass
class TurnResult:
    case: str
    message: str
    expect: dict
    seen: dict
    fields: dict[str, bool]
    calls: int = 0  # chat replies relayed
    parsed: int = 0  # of those, replies that parse as an intent
    error: str | None = None  # an AgentError code that ended the turn
    seconds: list[float] = field(default_factory=list)

    @property
    def wants_panel(self) -> bool:
        return self.expect.get("kind", "panel") == "panel"

    @property
    def correct(self) -> bool:
        return all(self.fields.values())


# (case id, turn index, the chat request) -> the model's raw reply
Answer = Callable[[str, int, dict], str]


def run_case(user, case: dict, answer: Answer) -> list[TurnResult]:
    """Drive one case through the real workflow. Embedding requests are skipped: the
    evaluation has no search index, so merchants are matched by name only."""
    names = {
        str(pk): name for pk, name in Category.objects.filter(user=user).values_list("id", "name")
    }
    token, results = None, []
    for index, turn in enumerate(case["turns"]):
        result = TurnResult(case["id"], turn["message"], turn["expect"], {"kind": "none"}, {})
        try:
            response = service.turn(user, turn["message"], token, {}, None)
            while response["status"] == "needs_model":
                request = response["request"]
                if request["kind"] == "embed":
                    response = service.step(user, response["token"], skip=True)
                    continue
                reply = answer(case["id"], index, request)
                result.calls += 1
                try:
                    parse_intent(reply)
                    result.parsed += 1
                except AgentError:
                    pass
                response = service.step(user, response["token"], reply=reply)
            token = response["token"]
            result.seen = observed(response["outcome"], names)
        except AgentError as problem:
            result.error = problem.code
        result.fields = score(turn["expect"], result.seen)
        results.append(result)
    return results


def golden_answer(cases: list[dict]) -> Answer:
    by_id = {case["id"]: case for case in cases}

    def answer(case_id: str, index: int, request: dict) -> str:
        return golden_reply(by_id[case_id]["turns"][index]["golden"])

    return answer
