"""LLM-as-a-judge for answers, validated against a person's labels: the labelling sheet.

A judge model's scores mean something only if they agree with a person's. So a person first labels
a sample of answers by hand, on the same rubric the judge gets. This module builds that sheet from
a saved answers run (see ai/eval/answers.py): every answer with exactly what the model was given.

The sheet leaves out the automated checks' verdicts and the expected rows on purpose: seeing them
would steer the labels, and the labels must be an independent human judgment.
"""

import json
import re
from dataclasses import dataclass
from decimal import Decimal

import numpy as np

from . import answers, results

RUBRIC_VERSION = "judge-rubric-v1"
# The same words go to the person labelling and, later, to the judge model, so they score the same.
RUBRIC = """\
**Faithful (1-5): is everything the answer says supported by what the model was given?**
Check each amount, date, count, name and total against the transactions and the summary line.
Judge only what the answer says, not what it leaves out (that belongs in Relevant).

- 5: every fact is supported.
- 4: a small slip that changes no fact (a name reworded, a category guessed).
- 3: one fact is wrong or unsupported (a wrong date, a count the model worked out itself).
- 2: a fact that matters is wrong: a total that isn't the summary's, or several wrong facts.
- 1: mostly made up, or it contradicts the transactions.

**Relevant (1-5): does it answer the question that was asked, fully and clearly?**

- 5: answers it directly and completely.
- 4: answers it, but misses a small part, or is hard to follow.
- 3: answers only part of it.
- 2: mostly about something else.
- 1: doesn't answer it.

**When the transactions don't match the question** (the "nothing to find" items): the right
answer says it couldn't find anything. Faithful 5 and Relevant 5 if it says so without inventing
facts; Faithful 1 if it presents unrelated rows as the answer."""

EXAMPLES = {
    "salary": {
        "faithful": 5,
        "relevant": 4,
        "note": "Every date it gives is right and cited. But it lists 10 of the 12 credits "
        "(2025-11-01 and 2025-12-01 are missing), so it isn't complete: Relevant 4, not 5. "
        "Leaving facts out doesn't lower Faithful.",
    },
    "haircuts": {
        "faithful": 2,
        "relevant": 4,
        "note": "The four amounts are right, but it adds them up itself and calls ₹2878.16 the "
        "total; the summary says ₹4387.45 over 5 haircuts (row 5, ₹712.29, is left out). A "
        "wrong total is a fact that matters: Faithful 2. It does answer the question, though "
        "repetitively: Relevant 4.",
    },
    "piano": {
        "faithful": 5,
        "relevant": 5,
        "note": "Nothing matches, and it says so, explaining why the tuition rows don't count. "
        "It invents nothing.",
    },
}
_ROW = re.compile(r"^\[(\d+)\] (\S+) \| (\w+) \| (₹[\d.]+) \| ([^|]*) \| (.*)$")


@dataclass(frozen=True)
class Item:
    question_id: str
    kind: str
    question: str
    period: str  # "2025-11-01 to 2026-10-15"
    summary: str  # the summary line the model was given
    rows: list[tuple[str, ...]]  # (n, date, type, amount, category, text)
    answer: str
    unrelated: bool  # a no-answer question given only unrelated rows
    answering: tuple[int, ...] = ()  # the shown rows that answer the question (the reference)


def _parse_prompt(content: str) -> tuple[str, str, list[tuple[str, ...]], str]:
    period = re.search(r"The search covered (\S+) to (\S+?)\.", content)
    summary = next(line for line in content.splitlines() if line.startswith("Summary of all"))
    question = re.search(r"^Question: (.*)$", content, re.M)[1]
    rows = [m.groups() for line in content.splitlines() if (m := _ROW.match(line))]
    return f"{period[1]} to {period[2]}", summary, rows, question


def items_from_run(label: str) -> list[Item]:
    """Every answer of a saved run, with the prompt it was given. The prompts are rebuilt by
    replaying the run (the search is deterministic), so nothing calls a model."""
    saved = results.load("answers", label)
    stored = iter(answers.current_records(saved["results"]))
    prompts = []

    def chat(messages: list[dict]) -> tuple[str, list[int] | None]:
        prompts.append(messages[-1]["content"])
        return next(stored)["answer"], None

    found = answers.run(chat, answer_format=saved["meta"].get("answer_format", "text"))
    items = []
    for result, prompt in zip(found, prompts, strict=True):
        period, summary, rows, question = _parse_prompt(prompt)
        items.append(
            Item(
                question_id=result.question,
                kind=result.kind,
                question=question,
                period=period,
                summary=summary,
                rows=rows,
                answer=result.answer,
                unrelated=result.said_not_found is not None,
                answering=tuple(result.answering_rows),
            )
        )
    return items


def sample(items: list[Item], count: int, unrelated: int, exclude: set[str]) -> list[Item]:
    """An even spread: `count - unrelated` answers across the question types, plus `unrelated`
    answers to no-answer questions. Deterministic: sorted by type and id, then every k-th."""

    def every(pool: list[Item], n: int) -> list[Item]:
        pool = sorted(pool, key=lambda i: (i.kind, i.question_id))
        step = len(pool) / n
        return [pool[int(k * step)] for k in range(n)]

    kept = [i for i in items if i.question_id not in exclude]
    return every([i for i in kept if not i.unrelated], count - unrelated) + every(
        [i for i in kept if i.unrelated], unrelated
    )


def render_item(number: str, item: Item, filled: dict | None = None) -> str:
    rows = "\n".join(
        f"| {n} | {day} | {kind} | {amount} | {category.strip()} | {text.strip()} |"
        for n, day, kind, amount, category, text in item.rows
    )
    quoted = "\n".join(f"> {line}" if line else ">" for line in item.answer.strip().splitlines())
    filled = filled or {}
    return "\n".join(
        [
            f"### {number} · `{item.question_id}`",
            "",
            f"**Question:** {item.question}",
            "",
            f"**The model was given:** search period {item.period}. {item.summary}",
            "",
            f"<details><summary>The {len(item.rows)} transactions it was shown</summary>",
            "",
            "| # | Date | Type | Amount | Category | Text |",
            "|---|---|---|---|---|---|",
            rows,
            "",
            "</details>",
            "",
            "**The model's answer:**",
            "",
            quoted,
            "",
            f"- Faithful (1-5): {filled.get('faithful', '')}",
            f"- Relevant (1-5): {filled.get('relevant', '')}",
            f"- Note: {filled.get('note', '')}",
            "",
        ]
    )


TUNING, HELD_OUT = "L", "H"  # item number prefixes: the set prompts are tuned on, and the test


def render_sheet(
    run_label: str,
    items: list[Item],
    count: int = 50,
    unrelated: int = 8,
    exclude: set[str] = frozenset(),
    prefix: str = TUNING,
) -> str:
    """A sheet of `count` answers to label. A held-out sheet (prefix H) leaves out the answers
    already labelled (`exclude`), so a judge prompt tuned on the first sheet is tested on
    answers it was never tuned on."""
    by_id = {item.question_id: item for item in items}
    chosen = sample(items, count, unrelated, exclude=set(EXAMPLES) | set(exclude))
    examples = [
        render_item(f"Example {n}", by_id[qid], labels)
        for n, (qid, labels) in enumerate(EXAMPLES.items(), start=1)
    ]
    to_label = [render_item(f"{prefix}{n:02d}", item) for n, item in enumerate(chosen, start=1)]
    title = "held-out answers" if prefix == HELD_OUT else "answer quality"
    return "\n".join(
        [
            f"# Labelling sheet: {title}",
            "",
            f"From the saved answers run `{run_label}`; rubric `{RUBRIC_VERSION}`. All data is "
            "fictional. Your scores are the reference that a judge model is later checked "
            "against, so score what you see and don't look anything up elsewhere.",
            "",
            f"**How to fill it in:** for each item from {prefix}01, read the question, open the "
            "transactions the model was shown, then score the answer. Write one number after "
            "each colon. The note is optional: a few words on why, if a score isn't 5.",
            "",
            f"{len(chosen) - unrelated} items are ordinary questions; the last {unrelated} are "
            "questions with nothing to find, where the model was shown unrelated rows.",
            "",
            "## Rubric",
            "",
            RUBRIC,
            "",
            f"## Worked examples (already scored, not part of the {len(chosen)})",
            "",
            *examples,
            "## Items to label",
            "",
            *to_label,
        ]
    )


_LABEL = re.compile(
    rf"^### ([{TUNING}{HELD_OUT}])\d+ · `([^`]+)`.*?"
    r"^- Faithful \(1-5\): *(\d?)\s*$.*?^- Relevant \(1-5\): *(\d?)\s*$",
    re.M | re.S,
)


def read_labels(sheet: str) -> dict[str, dict]:
    """{question id: {"faithful": int | None, "relevant": int | None, "held_out": bool}} from one
    or more filled sheets. Only the numbered items (L01, H01, ...) count; the worked examples
    are not labels."""
    labels = {}
    for prefix, question_id, faithful, relevant in _LABEL.findall(sheet):
        labels[question_id] = {
            "faithful": int(faithful) if faithful else None,
            "relevant": int(relevant) if relevant else None,
            "held_out": prefix == HELD_OUT,
        }
    return labels


# --- the judge model ---------------------------------------------------------------------------
# It gets the same rubric as the person, the same view of each answer, and the worked examples'
# scores and reasons. It writes its reason before its scores, so it checks the facts first.

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "faithful": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "relevant": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["reason", "faithful", "relevant"],
}
# num_predict caps a reply that loops instead of closing its JSON (minutes of CPU otherwise).
JUDGE_OPTIONS = {"temperature": 0, "seed": 2026, "num_ctx": 4096, "num_predict": 1024}
METRICS = ("faithful", "relevant")
RELIABLE_KAPPA = 0.6  # "substantial" agreement: below it, a judge is not used


def _judge_system() -> str:
    examples = "\n".join(
        f"- {qid}: Faithful {e['faithful']}, Relevant {e['relevant']}. {e['note']}"
        for qid, e in EXAMPLES.items()
    )
    return (
        "You grade one answer that a finance assistant gave about the user's own bank "
        "transactions. You see the question, exactly what the assistant was given (the search "
        "period, a summary line and the numbered transactions) and its answer. Grade the answer "
        f"with this rubric:\n\n{RUBRIC}\n\nHow the rubric was applied to three answers:\n"
        f"{examples}\n\nCheck every amount, date, count and total in the answer against the "
        "transactions and the summary before you score. Write a short reason first, then the "
        "two scores. Reply with JSON only."
    )


def judge_messages(item: Item) -> list[dict]:
    rows = "\n".join(
        f"[{n}] {day} | {kind} | {amount} | {category.strip()} | {text.strip()}"
        for n, day, kind, amount, category, text in item.rows
    )
    user = (
        f"Question: {item.question}\n\nThe assistant was given: search period {item.period}. "
        f"{item.summary}\n<transactions>\n{rows}\n</transactions>\n\n"
        f"The assistant's answer:\n<answer>\n{item.answer.strip()}\n</answer>"
    )
    return [{"role": "system", "content": _judge_system()}, {"role": "user", "content": user}]


def parse_judgment(reply: str) -> dict:
    """{"faithful", "relevant", "reason"} from the judge's reply. Raises ValueError if it isn't
    the shape the schema asks for."""
    data = json.loads(reply)
    scores = {name: data[name] for name in METRICS}
    if not all(isinstance(v, int) and 1 <= v <= 5 for v in scores.values()):
        raise ValueError(f"scores out of range: {scores}")
    return {**scores, "reason": str(data.get("reason", ""))[:500]}


# --- the checked judge: one criterion per call, grounded in exact checks ----------------------
# A small model grades better with one question at a time, and it can't reliably scan a table or
# add up amounts. So a program first checks every amount, date and citation in the answer against
# what the assistant was given, and groups the rows by payee; the model gets these exact facts and
# decides only what a program can't (is this row really a refund? does the answer cover what the
# question asks?). For faithfulness, the model lists errors and code turns them into the rubric's
# score, so the same errors always give the same score.

_AMOUNT = re.compile(r"₹\s?(\d[\d,]*(?:\.\d+)?)")
_CITATION = re.compile(r"\[(\d{1,3})\]")
_SENTENCE_END = re.compile(r"[.!?]\s|\n")
NEAR = 60  # characters between an amount and a citation that belongs to it
_SUMMARY = re.compile(
    r"Summary of all (\d+) matching transactions: debits total ₹([\d.]+), "
    r"credits total ₹([\d.]+)"
)
_WORD = re.compile(r"[a-z0-9₹.]+")


def _money(text: str) -> Decimal:
    return Decimal(text.replace(",", "").rstrip(".")).quantize(Decimal("0.01"))


def _row_list(numbers: list[int]) -> str:
    """[1, 2, 3, 5] -> "rows 1-3, 5"."""
    spans, start = [], None
    for k, n in enumerate(numbers):
        if start is None:
            start = n
        if k + 1 == len(numbers) or numbers[k + 1] != n + 1:
            spans.append(f"{start}" if start == n else f"{start}-{n}")
            start = None
    return ("row " if len(numbers) == 1 else "rows ") + ", ".join(spans)


def payee_groups(item: Item) -> list[str]:
    """The rows grouped by payee (the first two words of the text) and type, with how many there
    are and their amounts, so counting needs no scanning."""
    groups: dict[tuple[str, str], list[tuple[int, Decimal]]] = {}
    for n, _, kind, amount, _, text in item.rows:
        payee = " ".join(text.split()[:2])
        groups.setdefault((payee, kind), []).append((int(n), _money(amount.lstrip("₹"))))
    lines = []
    for (payee, kind), members in groups.items():
        amounts = {a for _, a in members}
        each = (
            f"₹{amounts.pop()} each" if len(amounts) == 1 else f"₹{min(amounts)} to ₹{max(amounts)}"
        )
        count = len(members)
        lines.append(
            f"- {payee} ({kind}): {count} transaction{'s' * (count > 1)}, "
            f"{_row_list(sorted(n for n, _ in members))}, {each}"
        )
    return lines


def miscited(answer: str, amounts: dict[int, Decimal]) -> list[str]:
    """Row amounts cited next to a row with a different amount. A citation belongs to an amount
    when it is in the same sentence, within NEAR characters before or after it ("₹500 [2]" and
    "on [2], ₹500" both cite row 2); it is a miscitation only if no such citation is right."""
    cites = [(m.start(), m.end(), int(m[1])) for m in _CITATION.finditer(answer)]
    checks = []
    for found in _AMOUNT.finditer(answer):
        amount = _money(found[1])
        if amount not in amounts.values():
            continue  # not a row amount: the amount checks cover it
        near = []
        for start, end, n in cites:
            gap = (
                answer[found.end() : start] if start >= found.end() else answer[end : found.start()]
            )
            if len(gap) <= NEAR and not _SENTENCE_END.search(gap) and n in amounts:
                near.append((len(gap), n))
        if near and all(amounts[n] != amount for _, n in near):
            n = min(near)[1]
            checks.append(f"- ₹{amount} next to [{n}]: row {n} is ₹{amounts[n]}, not ₹{amount}")
    return checks


def fact_checks(item: Item) -> list[str]:
    """Exact checks of the answer: where each amount and date in it comes from, and citations
    that point at a row with a different amount. Computed from what the assistant was given."""
    rows = [(int(n), day, _money(amount.lstrip("₹"))) for n, day, _, amount, _, _ in item.rows]
    summary = _SUMMARY.search(item.summary)
    totals = {"debit": _money(summary[2]), "credit": _money(summary[3])} if summary else {}
    checks = []
    for amount in dict.fromkeys(_money(raw) for raw in _AMOUNT.findall(item.answer)):
        where = [f"the summary's {kind} total" for kind, t in totals.items() if t and t == amount]
        matching = [n for n, _, a in rows if a == amount]
        if matching:
            where.append(f"the amount of {_row_list(matching)}")
        checks.append(
            f"- ₹{amount}: "
            + (" and ".join(where) if where else "in no row and not a summary total")
        )
    checks += miscited(item.answer, {n: a for n, _, a in rows})
    known_days = {day for _, day, _ in rows}
    for year, month, day in sorted(
        answers.facts(item.answer).dates, key=lambda d: (d[0] or 0, d[1], d[2])
    ):
        stamp = f"{year}-{month:02d}-{day:02d}" if year else f"--{month:02d}-{day:02d}"
        matching = [n for n, d, _ in rows if d == stamp or (not year and d.endswith(stamp[1:]))]
        in_period = stamp in item.period or stamp in item.summary
        if matching:
            checks.append(f"- {stamp}: the date of {_row_list(matching)}")
        elif not in_period and stamp not in known_days:
            checks.append(f"- {stamp}: the date of no row")
    if totals:
        checks.append(
            f"- The only totals given: debits ₹{totals['debit']}, credits ₹{totals['credit']}, "
            f"over all {summary[1]} matching transactions. An amount the answer presents as a "
            "total that isn't one of these is a wrong_total."
        )
    return checks


def _given(item: Item) -> str:
    rows = "\n".join(
        f"[{n}] {day} | {kind} | {amount} | {category.strip()} | {text.strip()}"
        for n, day, kind, amount, category, text in item.rows
    )
    return (
        f"Question: {item.question}\n\nThe assistant was given: search period {item.period}. "
        f"{item.summary}\n<transactions>\n{rows}\n</transactions>\n\n"
        "The same transactions grouped by payee (exact, made by a program):\n"
        + "\n".join(payee_groups(item))
    )


SEVERITIES = ("minor", "wrong", "wrong_total", "unrelated")
FAITHFUL_SCHEMA = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "errors": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {"type": "string"},
                    "problem": {"type": "string"},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                },
                "required": ["quote", "problem", "severity"],
            },
        },
    },
    "required": ["analysis", "errors"],
}
FAITHFUL_SYSTEM = """\
You check one answer that a finance assistant gave about the user's own bank transactions. You \
check only one thing: is everything the answer SAYS supported by what the assistant was given \
(the numbered transactions and the summary line)?

These are NOT errors, so never list them: rows the answer leaves out, a missing total or missing \
dates, true extra detail, the order of a list, a name written in different case or spacing.

These are errors. Give each one a severity:
- minor: a small slip that changes no fact: a name or category reworded or guessed, a row range \
such as "[1] to [10]" when the rows are 1-12.
- wrong: one fact is wrong or unsupported: a wrong amount, date or count (says 10 payments when \
there are 11), a start date that isn't the first payment's, a row called something its text \
doesn't say, a citation that points at a row with a different amount.
- wrong_total: an amount the answer presents as a total, or as the sum of several rows, that \
isn't the summary's total; a sum the assistant worked out itself counts.
- unrelated: the answer presents rows that don't match the question as its answer (a shop \
refund presented as a gas deposit refund), or calls the rows something they aren't throughout \
(credit card bills called gym payments).

If no row matches the question and the answer says it found nothing, that is correct: no errors.

The automatic checks under the answer are exact. Trust them: an amount "in no row and not a \
summary total" is an error (wrong_total if the answer calls it a total), and an amount or date \
they match to a row is right. Use the payee groups to check counts.

Reply with JSON. First "analysis": go through the answer's amounts, dates, counts, totals and \
what it calls each row. Then "errors": one entry per error, with "quote" (the exact words from \
the answer), "problem" and "severity". An empty list if everything it says is supported."""


def faithful_messages(item: Item) -> list[dict]:
    checks = fact_checks(item) or ["- the answer has no amounts or dates"]
    user = (
        f"{_given(item)}\n\nThe assistant's answer:\n<answer>\n{item.answer.strip()}\n</answer>\n\n"
        "Automatic checks of the answer's amounts, dates and citations (exact):\n"
        + "\n".join(checks)
    )
    return [{"role": "system", "content": FAITHFUL_SYSTEM}, {"role": "user", "content": user}]


def _quoted(quote: str, answer: str) -> bool:
    """True if most of the quote's words are in the answer: a model that complains about
    something the answer doesn't say can't quote it."""
    said = set(_WORD.findall(answer.lower()))
    words = _WORD.findall(quote.lower())
    return bool(words) and sum(w in said for w in words) / len(words) >= 0.6


def faithful_score(errors: list[dict]) -> int:
    """The rubric's faithfulness scale, from the errors found."""
    kinds = [error["severity"] for error in errors]
    wrong = kinds.count("wrong") + kinds.count("wrong_total")
    if "unrelated" in kinds:
        return 1
    if "wrong_total" in kinds or wrong >= 2:
        return 2
    if wrong == 1:
        return 3
    return 4 if "minor" in kinds else 5


def parse_faithful(reply: str, item: Item) -> dict:
    data = json.loads(reply)
    errors = [
        {k: str(e[k])[:200] for k in ("quote", "problem", "severity")} for e in data["errors"]
    ]
    if any(e["severity"] not in SEVERITIES for e in errors):
        raise ValueError(f"unknown severity in {errors}")
    kept = [e for e in errors if e["severity"] == "unrelated" or _quoted(e["quote"], item.answer)]
    return {
        "faithful": faithful_score(kept),
        "faithful_errors": kept,
        "faithful_dropped": [e for e in errors if e not in kept],
        "faithful_analysis": str(data.get("analysis", ""))[:800],
    }


RELEVANT_SCHEMA = {
    "type": "object",
    "properties": {
        "wants": {"type": "string"},
        "matching_rows": {"type": "string"},
        "analysis": {"type": "string"},
        "relevant": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["wants", "matching_rows", "analysis", "relevant"],
}
RELEVANT_SYSTEM = """\
You check one answer that a finance assistant gave about the user's own bank transactions. You \
check only one thing: does it answer the question that was asked, fully and clearly? Another \
check looks at whether its facts are right, so don't grade that here.

Work in three steps:
1. "wants": what the question asks for: a total ("how much"), dates ("when"), the payments, \
which services, or whether something exists at all.
2. "matching_rows": the numbered rows whose text really is what the question is about. Rows that \
only look similar don't count: a train ticket isn't a flight, health insurance isn't life \
cover, a shop refund isn't a gas deposit refund. Write "none" if no row matches.
3. "analysis": compare the answer with what the question wants and with the matching rows.

Then "relevant", on this scale:
- 5: gives what the question wants and covers every matching row. A total, or a clear summary \
such as "₹1500 every month from November 2025 to October 2026", covers the rows it describes.
- 4: answers it, but misses a small part (one or two matching rows), or is hard to follow.
- 3: answers only part of it: misses several matching rows, or gives no total when the question \
asks how much.
- 2: mostly about something else, such as rows that don't match presented as the answer.
- 1: doesn't answer it, such as saying nothing matches when rows do match.

If no row matches: 5 if the answer says it found nothing, 2 if it presents other rows as the \
answer. Reply with JSON."""


def relevant_messages(item: Item) -> list[dict]:
    user = f"{_given(item)}\n\nThe assistant's answer:\n<answer>\n{item.answer.strip()}\n</answer>"
    return [{"role": "system", "content": RELEVANT_SYSTEM}, {"role": "user", "content": user}]


def parse_relevant(reply: str) -> dict:
    data = json.loads(reply)
    score = data["relevant"]
    if not (isinstance(score, int) and 1 <= score <= 5):
        raise ValueError(f"score out of range: {score}")
    return {
        "relevant": score,
        "relevant_rows": str(data.get("matching_rows", ""))[:200],
        "relevant_analysis": str(data.get("analysis", ""))[:800],
    }


# --- the reference-guided judge ----------------------------------------------------------------
# A small model can't tell reliably which of 20 rows really answer the question (a train ticket
# isn't a flight), and most wrong answers go wrong exactly there: a count, a first date or a
# "total" over the wrong rows. The evaluation set knows which shown rows answer each question, so
# the judge is told (reference-guided grading). That needs a reference, so it grades evaluation
# answers only. Code also applies the rubric where it is mechanical: an amount in no row, and a
# question no shown row answers.

_TOTAL_WORDS = re.compile(r"total|\bsum\b|altogether|in all|overall|combined", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def says_not_found(item: Item) -> bool:
    return bool(answers.NOT_FOUND.search(item.answer))


def reference_facts(item: Item) -> list[str]:
    """Which shown rows answer the question, how many and over which dates."""
    if not item.answering:
        return ["- No row answers the question: every row shown is about something else."]
    days = {int(n): day for n, day, *_ in item.rows}
    dates = sorted(days[n] for n in item.answering if n in days)
    count = len(item.answering)
    verb = "answers" if count == 1 else "answer"
    return [
        f"- {_row_list(list(item.answering)).capitalize()} {verb} the question: {count} "
        f"transaction{'s' * (count > 1)}, dated {dates[0]} to {dates[-1]}. Every other row shown "
        "is about something else."
    ]


# How the "nothing found" fact is worded. v3's "It says it found nothing: no." was misread as the
# answer saying it found nothing, so v4 states it as a plain sentence either way.
NOT_FOUND_FACT = {
    "v3": ("- It says it found nothing: yes.", "- It says it found nothing: no."),
    "v4": (
        "- The answer says no transaction matches.",
        "- The answer gives transactions; it does not say that none match.",
    ),
}
REFERENCE_PROMPTS = tuple(NOT_FOUND_FACT)  # the prompts given the reference


def coverage_facts(item: Item, prompt: str = "v3", counts: bool = True) -> list[str]:
    """What the answer cites, compared with the reference. `counts` adds how many answering
    rows it cites: a relevance fact, which v4 keeps out of the faithfulness check."""
    cited = set(answers.cited_numbers(item.answer))
    lines = []
    if item.answering and counts:
        missing = sorted(set(item.answering) - cited)
        lines.append(
            f"- The answer cites {len(item.answering) - len(missing)} of the "
            f"{len(item.answering)} answering rows"
            + (f"; it doesn't cite {_row_list(missing)}." if missing else ".")
        )
    texts = {int(n): text.strip() for n, *_, text in item.rows}
    outside = sorted(n for n in cited if n in texts and n not in item.answering)
    if outside:
        lines.append(
            "- It also cites rows that don't answer the question: "
            + "; ".join(f"[{n}] {texts[n]}" for n in outside[:8])
        )
    said, gave = NOT_FOUND_FACT[prompt]
    lines.append(said if says_not_found(item) else gave)
    return lines


def unsupported_amounts(item: Item) -> list[dict]:
    """Errors code is sure of: each amount in the answer that is in no row and isn't a summary
    total. One its sentence calls a total (or a sum) is a wrong total."""
    allowed = {_money(amount.lstrip("₹")) for *_, amount, _, _ in item.rows}
    if summary := _SUMMARY.search(item.summary):
        allowed |= {_money(summary[2]), _money(summary[3])}
    errors, seen = [], set()
    for sentence in _SENTENCES.split(item.answer):
        for raw in _AMOUNT.findall(sentence):
            amount = _money(raw)
            if amount in allowed or amount in seen:
                continue
            seen.add(amount)
            errors.append(
                {
                    "quote": sentence.strip()[:200],
                    "problem": f"₹{amount} is in no row and isn't a summary total",
                    "severity": "wrong_total" if _TOTAL_WORDS.search(sentence) else "wrong",
                }
            )
    return errors


FAITHFUL_V3_SYSTEM = """\
You check one answer that a finance assistant gave about the user's own bank transactions. You \
check only one thing: is everything the answer SAYS supported by what the assistant was given \
(the numbered transactions and the summary line)?

You also get a reference, which is exact: which numbered rows really answer the question. Use it:
- a count in the answer ("4 refills", "you paid 3 times") that differs from the number of \
answering rows is wrong;
- a first or last date that isn't the first or last answering row's date is wrong;
- a row outside the reference that the answer presents as part of its answer (a train ticket \
called a flight, a health premium called life cover, a music plan called the streaming service) \
is wrong; if most of what it presents is outside the reference, that is unrelated.

These are NOT errors, so never list them: answering rows the answer leaves out, a missing total \
or missing dates, true extra detail, the order of a list, a name written in different case or \
spacing.

These are errors. Give each one a severity:
- minor: a small slip that changes no fact: a name or category reworded or guessed, a row range \
such as "[1] to [10]" when the answering rows are 1-12.
- wrong: one fact is wrong or unsupported, as above, or a citation that points at a row with a \
different amount.
- wrong_total: an amount the answer presents as a total, or as the sum of several rows, that \
isn't the summary's total; a sum the assistant worked out itself counts.
- unrelated: the answer presents rows that don't answer the question as its answer, throughout.

If no row answers the question and the answer says it found nothing, that is correct: no errors.

Reply with JSON. First "analysis": go through the answer's counts, dates, totals and what it \
calls each row, against the reference. Then "errors": one entry per error, with "quote" (the \
exact words from the answer), "problem" and "severity". An empty list if everything it says is \
supported."""

RELEVANT_V3_SCHEMA = {
    "type": "object",
    "properties": {
        "wants": {"type": "string"},
        "analysis": {"type": "string"},
        "relevant": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
    },
    "required": ["wants", "analysis", "relevant"],
}
RELEVANT_V3_SYSTEM = """\
You check one answer that a finance assistant gave about the user's own bank transactions. You \
check only one thing: does it answer the question that was asked, fully and clearly? Another \
check looks at whether its facts are right, so don't grade that here.

You also get a reference, which is exact: which numbered rows really answer the question, and \
how many of them the answer cites.

Work in two steps:
1. "wants": what the question asks for: a total ("how much"), dates ("when"), the payments, \
which services, or whether something exists at all.
2. "analysis": compare the answer with what the question wants and with the answering rows.

Then "relevant", on this scale:
- 5: gives what the question wants and covers every answering row. A total, or a clear summary \
such as "₹1500 every month from November 2025 to October 2026", covers the rows it describes \
even if it doesn't cite each one.
- 4: answers it, but misses a small part (one or two answering rows), or is hard to follow.
- 3: answers only part of it: misses several answering rows, or gives no total when the question \
asks how much.
- 2: mostly about something else: rows outside the reference presented as the answer.
- 1: doesn't answer it.

Reply with JSON."""
# v4: the reference gives no cited-row count (a 7B judge read every uncited row as missing, even
# under a summary that covers it), so coverage is judged from what the answer says.
RELEVANT_V4_SYSTEM = """\
You check one answer that a finance assistant gave about the user's own bank transactions. You \
check only one thing: does it answer the question that was asked, fully and clearly? Another \
check looks at whether its facts are right, so don't grade that here.

You also get a reference, which is exact: which numbered rows really answer the question, how \
many there are and the dates they span.

Work in two steps:
1. "wants": what the question asks for: a total ("how much"), dates ("when"), the payments, \
which services, or whether something exists at all.
2. "analysis": compare the answer with what the question wants, and what it covers with the \
answering rows: their number and the dates they span.

Judge coverage from what the answer SAYS, not from which row numbers it cites. A total, or a \
clear summary such as "₹1500 every month from November 2025 to October 2026", covers every row it \
describes. An answer that lists 4 payments when the reference has 5 misses one.

Then "relevant", on this scale:
- 5: gives what the question wants and covers every answering row.
- 4: answers it, but misses a small part (one or two answering rows), or is hard to follow.
- 3: answers only part of it: misses several answering rows, or gives no total when the question \
asks how much.
- 2: mostly about something else: rows outside the reference presented as the answer.
- 1: doesn't answer it.

Reply with JSON."""


def _reference_block(item: Item, prompt: str = "v3", counts: bool = True) -> str:
    return "Reference (exact, from the evaluation set):\n" + "\n".join(
        reference_facts(item) + coverage_facts(item, prompt, counts)
    )


def faithful_v3_messages(item: Item, prompt: str = "v3") -> list[dict]:
    checks = fact_checks(item) or ["- the answer has no amounts or dates"]
    reference = _reference_block(item, prompt, counts=prompt == "v3")
    user = (
        f"{_given(item)}\n\nThe assistant's answer:\n<answer>\n{item.answer.strip()}\n</answer>\n\n"
        f"{reference}\n\nAutomatic checks of the answer's amounts, dates and "
        "citations (exact):\n" + "\n".join(checks)
    )
    return [{"role": "system", "content": FAITHFUL_V3_SYSTEM}, {"role": "user", "content": user}]


def relevant_v3_messages(item: Item, prompt: str = "v3") -> list[dict]:
    user = (
        f"{_given(item)}\n\nThe assistant's answer:\n<answer>\n{item.answer.strip()}\n</answer>\n\n"
        f"{_reference_block(item, prompt, counts=prompt == 'v3')}"
    )
    system = RELEVANT_V3_SYSTEM if prompt == "v3" else RELEVANT_V4_SYSTEM
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _amounts_in(text: str) -> set[Decimal]:
    return {_money(raw) for raw in _AMOUNT.findall(text)}


def parse_faithful_v3(reply: str, item: Item) -> dict:
    """The model's errors plus the unsupported amounts code found, each error counted once."""
    scored = parse_faithful(reply, item)
    found = unsupported_amounts(item)
    by_code = set().union(*(_amounts_in(e["problem"]) for e in found)) if found else set()
    model = [e for e in scored["faithful_errors"] if not (_amounts_in(e["quote"]) & by_code)]
    errors = found + model
    return {**scored, "faithful": faithful_score(errors), "faithful_errors": errors}


def ruled(item: Item, prompt: str) -> dict:
    """Scores the rubric decides without a model: when no shown row answers the question, the
    right answer says it found nothing (relevant 5), and presenting rows as the answer is
    relevant 2 and faithful 1. Only for the reference-guided prompts."""
    if prompt not in REFERENCE_PROMPTS or item.answering:
        return {}
    if says_not_found(item):
        return {"relevant": 5, "relevant_rule": "no row answers; it says it found nothing"}
    rule = "no row answers; it presents rows as the answer"
    return {"relevant": 2, "relevant_rule": rule, "faithful": 1, "faithful_rule": rule}


# --- prompt versions ---------------------------------------------------------------------------

PROMPTS = {
    "v1": "both scores in one call, rubric and worked examples only",
    "v2": "one call per score; exact checks and payee groups given; faithfulness scored by code",
    "v3": "v2 plus the reference: which rows answer the question; mechanical rubric cases by code",
    "v4": "v3, the found-nothing fact worded plainly, no cited-row counts, coverage from words",
}
DEFAULT_PROMPT = "v2"


def call_metrics(prompt: str) -> tuple[str, ...]:
    """What each model call scores, in the order the calls are made."""
    return ("both",) if prompt == "v1" else METRICS


def judge_calls(item: Item, prompt: str) -> list[tuple[str, list[dict], dict]]:
    """(the metric it scores, messages, JSON schema) for each model call that scores one
    answer. A v1 call scores both metrics at once ("both"). A metric the rubric decides without
    a model (see `ruled`) has no call."""
    if prompt == "v1":
        return [("both", judge_messages(item), JUDGE_SCHEMA)]
    if prompt == "v2":
        return [
            ("faithful", faithful_messages(item), FAITHFUL_SCHEMA),
            ("relevant", relevant_messages(item), RELEVANT_SCHEMA),
        ]
    decided = ruled(item, prompt)
    calls = [
        ("faithful", faithful_v3_messages(item, prompt), FAITHFUL_SCHEMA),
        ("relevant", relevant_v3_messages(item, prompt), RELEVANT_V3_SCHEMA),
    ]
    return [call for call in calls if call[0] not in decided]


def read_reply(metric: str, reply: str, item: Item, prompt: str = DEFAULT_PROMPT) -> dict:
    """Parse one call's reply into the fields it adds to the item's cached judgment. Raises
    ValueError, KeyError or TypeError if the reply isn't the shape asked for."""
    if metric == "both":
        return parse_judgment(reply)
    if metric == "faithful":
        if prompt in REFERENCE_PROMPTS:
            return parse_faithful_v3(reply, item)
        return parse_faithful(reply, item)
    return parse_relevant(reply)


def cache_label(model: str, run: str, prompt: str = "v1") -> str:
    """The saved-run label for one judge model's scores of one answers run with one prompt."""
    slug = re.sub(r"[^a-z0-9]+", "-", model.lower()).strip("-")
    suffix = "" if prompt == "v1" else f"--{prompt}"
    return f"{slug}--{run}"[: 48 - len(suffix)].rstrip("-") + suffix


def load_judgments(model: str, run: str, prompt: str = "v1") -> dict:
    try:
        return results.load("judgments", cache_label(model, run, prompt))["items"]
    except FileNotFoundError:
        return {}


def panel(judgments: list[dict]) -> dict:
    """Several judges as one: per answer and metric, the mean of the judges' scores, a half
    rounded up. Only answers every judge scored on that metric."""
    combined: dict[str, dict] = {}
    for question_id in set.intersection(*(set(j) for j in judgments)) if judgments else ():
        for metric in METRICS:
            values = [j[question_id].get(metric) for j in judgments]
            if None not in values:
                mean = Decimal(sum(values)) / len(values)
                rounded = int(mean.quantize(Decimal(1), rounding="ROUND_HALF_UP"))
                combined.setdefault(question_id, {})[metric] = rounded
                rule = f"{metric}_rule"  # decided by the rubric for every judge: still a rule
                if all(rule in j[question_id] for j in judgments):
                    combined[question_id][rule] = judgments[0][question_id][rule]
    return combined


def save_judgments(model: str, run: str, items: dict, prompt: str = "v1") -> None:
    results.save(
        "judgments",
        cache_label(model, run, prompt),
        {"meta": results.metadata(judge=model, answers_run=run, rubric=RUBRIC_VERSION,
                                  prompt=prompt),
         "items": items},
        overwrite=True,
    )  # fmt: skip


# --- agreement ---------------------------------------------------------------------------------


def weighted_kappa(first: list[int], second: list[int], levels: int = 5) -> float:
    """Cohen's kappa with quadratic weights, for scores 1..levels: 1 is perfect agreement, 0 is
    what chance gives, and a near miss (4 vs 5) costs less than a far one (1 vs 5). NaN when it
    can't be computed (fewer than two items, or both raters give one score every time)."""
    if len(first) != len(second):
        raise ValueError("both raters must score the same items")
    if len(first) < 2:
        return float("nan")
    observed = np.zeros((levels, levels))
    for a, b in zip(first, second):
        observed[a - 1, b - 1] += 1
    observed /= observed.sum()
    expected = np.outer(observed.sum(axis=1), observed.sum(axis=0))
    i, j = np.indices((levels, levels))
    weights = (i - j) ** 2 / (levels - 1) ** 2
    chance = (weights * expected).sum()
    if chance == 0:
        return float("nan")
    return float(1 - (weights * observed).sum() / chance)


def agreement(reference: dict, judged: dict, metric: str, resamples: int = 1000) -> dict:
    """How well `judged` agrees with `reference` ({question id: {metric: score}}) on the items both
    scored: n, quadratic-weighted kappa with a bootstrap 95% interval, exact and within-1 rates."""
    ids = sorted(
        q for q in reference
        if reference[q].get(metric) is not None and judged.get(q, {}).get(metric) is not None
    )  # fmt: skip
    a = [reference[q][metric] for q in ids]
    b = [judged[q][metric] for q in ids]
    if not ids:
        return {"n": 0}
    rng = np.random.default_rng(2026)
    kappas = []
    for _ in range(resamples):
        pick = rng.integers(0, len(ids), len(ids))
        value = weighted_kappa([a[k] for k in pick], [b[k] for k in pick])
        if value == value:  # not NaN
            kappas.append(value)
    low, high = np.percentile(kappas, [2.5, 97.5]) if kappas else (float("nan"),) * 2
    return {
        "n": len(ids),
        "kappa": round(weighted_kappa(a, b), 3),
        "kappa_ci": [round(float(low), 3), round(float(high), 3)],
        "exact": round(sum(x == y for x, y in zip(a, b)) / len(ids), 3),
        "within_1": round(sum(abs(x - y) <= 1 for x, y in zip(a, b)) / len(ids), 3),
        "mean_reference": round(float(np.mean(a)), 2),
        "mean_judged": round(float(np.mean(b)), 2),
    }


def kappa_change(
    reference: dict, before: dict, after: dict, metric: str, resamples: int = 2000
) -> dict:
    """Did agreement with `reference` really change from `before` to `after`? A paired bootstrap
    over the answers all three scored: each resample draws the same answers for both judges, so
    the interval is for the change itself. "real" when the 95% interval leaves out zero."""
    ids = sorted(
        q
        for q in reference
        if all(s.get(q, {}).get(metric) is not None for s in (reference, before, after))
    )
    if len(ids) < 2:
        return {"n": len(ids)}
    ref, old, new = ([s[q][metric] for q in ids] for s in (reference, before, after))
    rng = np.random.default_rng(2026)
    changes = []
    for _ in range(resamples):
        pick = rng.integers(0, len(ids), len(ids))
        sample = [ref[k] for k in pick]
        change = weighted_kappa(sample, [new[k] for k in pick]) - weighted_kappa(
            sample, [old[k] for k in pick]
        )
        if change == change:  # not NaN
            changes.append(change)
    low, high = np.percentile(changes, [2.5, 97.5])
    first, second = weighted_kappa(ref, old), weighted_kappa(ref, new)
    return {
        "n": len(ids),
        "before": round(first, 3),
        "after": round(second, 3),
        "change": round(second - first, 3),
        "change_ci": [round(float(low), 3), round(float(high), 3)],
        "real": bool(low > 0 or high < 0),
    }
