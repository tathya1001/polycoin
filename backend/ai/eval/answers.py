"""Answer quality with a real chat model: the production prompt, on every evaluation question.

The checks need no judge model, so they are exact and repeatable:
- cites: the answer cites at least one transaction in the prompt ([n]);
- citation precision: the share of valid citations that point at a relevant row;
- invalid references: citations to a number that isn't in the prompt;
- made-up numbers: every amount, count and full date in the answer must appear in the prompt or
  the question (rule 3 says totals and counts come from the summary, so a sum the model worked out
  itself counts as made up too);
- totals: on a question about how much was spent, the answer must quote the summary's total. A
  wrong total is blamed on search if the summary was already wrong, else on the model;
- "not found": given only unrelated rows, the model says it found nothing.

Run with a local Ollama (dev machine, fictional data only): ai/test_rag_generation_eval.py.
"""

import calendar
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings

from ai.rag.answer import Source, build_messages, summarize
from ai.rag.periods import detect_period
from ai.rag.profiles import UNTUNED, profile_for
from insights.spec import resolve_period

from . import dataset
from .build_dataset import TODAY
from .evaluate import Evaluation, production_variant

# Citations as the page reads them (lib/rag.ts): "[3]" or a list such as "[1, 4]". A range such
# as "[1-10]" links nothing on the page, so it is not a citation, but its numbers aren't amounts.
CITATION = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
BRACKETED = re.compile(r"\[\d{1,3}(?:\s*[,–-]\s*\d{1,3})*\]")


def cited_numbers(text: str) -> list[int]:
    return [int(n) for group in CITATION.findall(text) for n in group.split(",")]


NOT_FOUND = re.compile(
    r"could(?: not|n't) find|not found|no (?:matching |relevant )?transactions?|"
    r"(?:does|do) not (?:show|contain|include)|no record|none of the",
    re.IGNORECASE,
)
# Questions whose answer is an amount: the summary's total must be quoted.
TOTAL_QUESTION = re.compile(r"\bhow much\b|\btotal\b|\bspen[dt]\b|\bkharcha\b|\bkitna\b", re.I)

_MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name} | {
    name.lower(): n for n, name in enumerate(calendar.month_abbr) if name
}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DAY_MONTH = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})\.?(?:,?\s+(\d{{4}}))?\b", re.I
)
_MONTH_DAY = re.compile(
    rf"\b({_MONTH})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", re.I
)
_NUMBER = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])")


@dataclass(frozen=True)
class Facts:
    """The numbers and full dates in a text. A date without a year is (None, month, day)."""

    numbers: frozenset[Decimal]
    dates: frozenset[tuple[int | None, int, int]]


def facts(text: str) -> Facts:
    """Citations are dropped first; dates are read and removed before the numbers, so a date's
    day and year are not counted as amounts."""
    text = BRACKETED.sub(" ", text)
    dates = set()

    def take(year, month, day):
        dates.add((int(year) if year else None, month, int(day)))
        return " "

    text = _ISO.sub(lambda m: take(m[1], int(m[2]), m[3]), text)
    text = _DAY_MONTH.sub(lambda m: take(m[3], _MONTHS[m[2].lower()], m[1]), text)
    text = _MONTH_DAY.sub(lambda m: take(m[3], _MONTHS[m[1].lower()], m[2]), text)
    numbers = set()
    for token in _NUMBER.findall(text):
        try:
            numbers.add(Decimal(token.replace(",", "")).normalize())
        except InvalidOperation:
            continue
    return Facts(frozenset(numbers), frozenset(dates))


def made_up(answer: str, allowed_text: str) -> list[str]:
    """Numbers and full dates in the answer that appear nowhere in `allowed_text`."""
    said, known = facts(answer), facts(allowed_text)
    known_days = {(month, day) for _, month, day in known.dates}
    # A year on its own ("in March 2026") is known if any known date has it.
    known_numbers = known.numbers | {Decimal(year) for year, _, _ in known.dates if year}
    wrong = [format(n, "f") for n in sorted(said.numbers - known_numbers)]
    for year, month, day in sorted(said.dates, key=lambda d: (d[0] or 0, d[1], d[2])):
        if (year, month, day) not in known.dates and (
            year is not None or (month, day) not in known_days
        ):
            wrong.append(f"{year or '?'}-{month:02d}-{day:02d}")
    return wrong


def quotes(answer: str, amount: str) -> bool:
    return Decimal(amount).normalize() in facts(answer).numbers


@dataclass
class Result:
    question: str
    kind: str
    answer: str
    cited: list[int]
    valid: int
    relevant_valid: int
    invalid: int
    made_up: list[str]
    total_question: bool = False
    summary_right: bool | None = None  # the summary's total equals the true total
    quotes_total: bool | None = None
    said_not_found: bool | None = None  # no-answer questions only
    answering_rows: list[int] = field(default_factory=list)  # shown rows that answer it
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)

    @property
    def error(self) -> str | None:
        """For a total question: None if right, else whose fault the wrong total is."""
        if not self.total_question:
            return None
        if not self.summary_right:
            return "retrieval"
        return None if self.quotes_total and not self.made_up else "generation"


def _sources(evaluation: Evaluation, ids: list[str]) -> list[Source]:
    rows = {row["id"]: row for row in evaluation.rows}
    texts = dict(zip(evaluation.ids, dataset.document_texts()))
    return [
        Source(
            n=n,
            transaction=row_id,
            date=date.fromisoformat(rows[row_id]["date"]),
            txn_type=rows[row_id]["txn_type"],
            amount=Decimal(rows[row_id]["amount"]),
            name=rows[row_id]["name"],
            category={"id": "", "name": rows[row_id]["category"], "color": ""},
            text=texts[row_id],
        )
        for n, row_id in enumerate(ids, start=1)
    ]


def _period(question: str, first: date) -> dict:
    detected = detect_period(question, TODAY)
    if detected:
        start, end = resolve_period(detected.date_filter, detected.date_filter, TODAY)
    else:
        start, end = first, TODAY
    return {"from": start.isoformat(), "to": end.isoformat()}


Chat = Callable[[list[dict]], tuple[str, list[int] | None]]  # messages -> (answer, citations)


def run(
    chat: Chat, sample: int | None = None, clock=None, answer_format: str = "text"
) -> list[Result]:
    """Every answerable question (or an even sample of them), plus every no-answer question.

    `chat` sends the messages and returns the answer text and, when the model returns them apart
    (structured answers), its citation numbers, else None. `answer_format` picks the prompt.
    """

    clock = clock or time.perf_counter
    evaluation = Evaluation()
    profile = profile_for(dataset.vectors()["model"])
    variant = production_variant(profile)
    first = min(date.fromisoformat(row["date"]) for row in evaluation.rows)
    texts = {q["id"]: q["question"] for q in dataset.questions()}
    answerable = [q for q in evaluation.questions if q.relevant]
    if sample:
        step = max(1, len(answerable) // sample)
        answerable = answerable[::step][:sample]
    results = []

    for question in answerable:
        text = texts[question.id]
        ids = evaluation.search(question, variant, profile, "hybrid")
        if not ids:  # production never calls the model with no matches
            continue
        sources = _sources(evaluation, ids)
        summary = summarize(sources)
        messages = build_messages(
            text, sources, summary, _period(text, first), TODAY, answer_format
        )
        started = clock()
        answer, numbers = chat(messages)
        elapsed = clock() - started
        shown = min(len(sources), settings.RAG_TOP_K)
        # What the page shows: the citations in the text, plus any a structured answer lists.
        cited = sorted(set(cited_numbers(answer)) | set(numbers or []))
        good = [n for n in cited if 1 <= n <= shown]
        relevant_type = {evaluation.amounts[r][0] for r in question.relevant}
        total_key = "debit_total" if relevant_type == {"debit"} else "credit_total"
        true_total = sum(
            (evaluation.amounts[r][1] for r in question.relevant), Decimal(0)
        ).quantize(Decimal("0.01"))
        is_total = bool(TOTAL_QUESTION.search(text)) and len(relevant_type) == 1
        allowed = " ".join(m["content"] for m in messages) + " " + text
        results.append(
            Result(
                question=question.id,
                kind=question.kind,
                answer=answer,
                cited=cited,
                valid=len(good),
                relevant_valid=sum(
                    1 for n in good if sources[n - 1].transaction in question.relevant
                ),
                invalid=len(cited) - len(good),
                made_up=made_up(answer, allowed),
                total_question=is_total,
                summary_right=Decimal(summary[total_key]) == true_total if is_total else None,
                quotes_total=quotes(answer, summary[total_key]) if is_total else None,
                answering_rows=[
                    n
                    for n in range(1, shown + 1)
                    if sources[n - 1].transaction in question.relevant
                ],
                seconds=round(elapsed, 2),
            )
        )

    # No-answer questions find nothing in production, so the model is never called. To test the
    # model's own "not found", give it the rows an untuned search ranks closest: all unrelated.
    for question in (q for q in evaluation.questions if not q.relevant):
        text = texts[question.id]
        sources = _sources(evaluation, evaluation.search(question, variant, UNTUNED, "vector")[:5])
        messages = build_messages(
            text, sources, summarize(sources), _period(text, first), TODAY, answer_format
        )
        started = clock()
        answer, _ = chat(messages)
        results.append(
            Result(
                question=question.id,
                kind=question.kind,
                answer=answer,
                cited=[],
                valid=0,
                relevant_valid=0,
                invalid=0,
                made_up=[],
                said_not_found=bool(NOT_FOUND.search(answer)),
                seconds=round(clock() - started, 2),
            )
        )
    return results


def summary(results: list[Result]) -> dict:
    answered = [r for r in results if r.said_not_found is None]
    unrelated = [r for r in results if r.said_not_found is not None]
    totals = [r for r in answered if r.total_question]
    valid = sum(r.valid for r in answered)
    cited = sum(r.valid + r.invalid for r in answered)

    def share(part, whole):
        return round(part / whole, 4) if whole else None

    return {
        "answers": len(answered),
        "cites": share(sum(1 for r in answered if r.valid), len(answered)),
        "citation precision": share(sum(r.relevant_valid for r in answered), valid),
        "invalid references": share(sum(r.invalid for r in answered), cited),
        "made-up-number rate": share(sum(1 for r in answered if r.made_up), len(answered)),
        "total questions": len(totals),
        "totals right": share(sum(1 for r in totals if r.error is None), len(totals)),
        "total errors from search": sum(1 for r in totals if r.error == "retrieval"),
        "total errors from the model": sum(1 for r in totals if r.error == "generation"),
        "not found when unrelated": share(sum(r.said_not_found for r in unrelated), len(unrelated)),
        "median seconds": sorted(r.seconds for r in answered)[len(answered) // 2]
        if answered
        else None,
    }


def as_records(results: list[Result]) -> list[dict]:
    return [{**asdict(r), "error": r.error} for r in results]


def current_records(records: list[dict]) -> list[dict]:
    """A saved run's records for the questions still in the dev set, in order, so replaying an
    older run lines its answers up with today's questions."""
    ids = {question["id"] for question in dataset.questions()}
    return [record for record in records if record["question"] in ids]
