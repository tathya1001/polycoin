"""Builds the retrieval evaluation set: rag_corpus.json and rag_questions.json.

    docker compose exec backend python manage.py build_rag_eval

Deterministic (fixed seed), so the files only change when this script does. Every merchant, UPI
handle and bank code is made up. Narrations follow Indian bank statement formats (UPI, NEFT, IMPS,
ACH, POS, ATM), and each row's name comes from the importer's own clean_name(), so the documents
are exactly what a real import would produce.

Each question's relevant rows are derived from the merchants that generated them, so the expected
answers can't drift from the data. After changing this file, run it, then re-embed with
`python manage.py embed_rag_eval`.
"""

import calendar
import json
import random
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from ai.rag.retriever import remove_stopwords, tokenize
from ai.scoring import prepare_text
from transactions.importer import clean_name

HERE = Path(__file__).parent
TODAY = date(2026, 10, 15)  # the evaluation's fixed "today"; the history ends here
FIRST_MONTH = date(2025, 11, 1)  # twelve months of history
SEED = 2026


@dataclass(frozen=True)
class Merchant:
    key: str  # what questions refer to
    name: str  # as it appears in the narration
    category: str  # one of the app's default categories
    fmt: str  # narration format, a key of the table in narration()
    low: int  # amount range in rupees
    high: int
    schedule: tuple  # ("monthly", day) | ("every", months, day) | ("times", count)
    txn_type: str = "debit"
    remark: str = ""
    notes: tuple = ()  # the user's own notes; one is picked for some rows


MERCHANTS = [
    # Regular payments.
    Merchant("rent", "MAPLE STREET HOMES", "Rent", "neft_dr", 22000, 22000, ("monthly", 3),
             remark="RENT"),
    Merchant("salary", "ACME CORP PAYROLL", "Salary", "neft_cr", 85000, 85000, ("monthly", 1),
             txn_type="credit", remark="SAL"),
    Merchant("power", "NORTHWIND POWER", "Bills", "ach", 900, 2600, ("monthly", 8),
             remark="ELECTRICITY BILL"),
    Merchant("mobile", "SKYLINE MOBILE", "Bills", "upi_dr", 399, 399, ("monthly", 12),
             remark="POSTPAID"),
    Merchant("gym", "FITZONE GYM", "Health", "upi_dr", 1500, 1500, ("monthly", 5),
             remark="MEMBERSHIP"),
    Merchant("cinestream", "CINESTREAM", "Entertainment", "ach", 199, 199, ("monthly", 15),
             remark="SUBSCRIPTION"),
    Merchant("emi", "NEXA FINANCE", "Others", "ach", 18500, 18500, ("monthly", 10),
             remark="HOME LOAN EMI"),
    Merchant("broadband", "FIBRELINK BROADBAND", "Bills", "upi_dr", 799, 799, ("every", 2, 18),
             remark="FIBRE PLAN"),
    Merchant("water", "AQUAFLOW WATER BOARD", "Bills", "ach", 300, 650, ("every", 3, 20),
             remark="WATER CHARGES"),
    Merchant("insurance", "SAFEGUARD INSURANCE", "Health", "ach", 4200, 4200, ("every", 3, 25),
             remark="PREMIUM"),
    Merchant("tunewave", "TUNEWAVE MUSIC", "Entertainment", "upi_dr", 119, 119, ("every", 2, 22),
             remark="SUBSCRIPTION"),
    Merchant("tutors", "BRAINY TUTORS", "Others", "neft_dr", 6000, 6000, ("every", 3, 7),
             remark="TUITION FEES"),
    Merchant("interest", "INTEREST CREDIT", "Others", "interest", 180, 420, ("every", 3, 30),
             txn_type="credit"),
    # Everyday spending.
    Merchant("tastybites", "TASTYBITES CAFE", "Food", "upi_dr", 180, 900, ("times", 10),
             notes=("lunch with team", "dinner")),
    Merchant("spiceroute", "SPICE ROUTE KITCHEN", "Food", "upi_dr", 400, 1800, ("times", 6)),
    Merchant("dosa", "DAILY DOSA", "Food", "pos", 90, 300, ("times", 6), notes=("breakfast",)),
    Merchant("biryani", "BIRYANI JUNCTION", "Food", "upi_dr", 250, 700, ("times", 5)),
    Merchant("coffee", "BREWBEAN COFFEE", "Food", "upi_dr", 150, 450, ("times", 8)),
    Merchant("greenleaf", "GREENLEAF GROCERS", "Groceries", "pos", 600, 3500, ("times", 8)),
    Merchant("freshbasket", "FRESHBASKET MART", "Groceries", "upi_dr", 300, 2200, ("times", 6),
             notes=("vegetables and fruits",)),
    Merchant("dailyneeds", "DAILYNEEDS STORE", "Groceries", "pos", 120, 900, ("times", 4)),
    Merchant("cabs", "CITYRIDE CABS", "Transport", "upi_dr", 120, 650, ("times", 8)),
    Merchant("fuel", "FUELSTOP PETROL", "Transport", "pos", 1000, 3000, ("times", 10)),
    Merchant("metro", "METRO CARD TOPUP", "Transport", "upi_dr", 200, 500, ("times", 4)),
    Merchant("rail", "RAILCONNECT TICKETS", "Transport", "upi_dr", 450, 2400, ("times", 3)),
    Merchant("airline", "SKYWAY AIRLINES", "Transport", "upi_dr", 4500, 9000, ("times", 2)),
    Merchant("hotel", "STAYEASY HOTELS", "Others", "upi_dr", 3200, 7500, ("times", 2)),
    Merchant("brightmart", "BRIGHTMART", "Shopping", "upi_dr", 500, 4000, ("times", 4)),
    Merchant("apparel", "THREADLINE APPAREL", "Shopping", "pos", 900, 4500, ("times", 3)),
    Merchant("gadgets", "GADGETZONE ELECTRONICS", "Shopping", "upi_dr", 2500, 32000,
             ("times", 2), notes=("new headphones", "laptop charger")),
    Merchant("cinestar", "CINESTAR SCREENS", "Entertainment", "upi_dr", 300, 900, ("times", 4)),
    Merchant("gamevault", "GAMEVAULT", "Entertainment", "upi_dr", 499, 2999, ("times", 2)),
    Merchant("pharmacy", "WELLCARE PHARMACY", "Health", "pos", 150, 1800, ("times", 5)),
    Merchant("clinic", "SUNRISE CLINIC", "Health", "upi_dr", 500, 1500, ("times", 3),
             remark="CONSULTATION"),
    Merchant("transfer", "R SAMPLE", "Transfer", "imps", 1000, 8000, ("times", 4),
             notes=("birthday gift", "split for trip")),
    Merchant("atm", "MG ROAD BRANCH", "Others", "atm", 2000, 10000, ("times", 5)),
    Merchant("refund", "BRIGHTMART", "Shopping", "upi_cr", 400, 2500, ("times", 3),
             txn_type="credit", remark="REFUND"),
]  # fmt: skip


def _digits(rng: random.Random, count: int) -> str:
    return "".join(rng.choice("0123456789") for _ in range(count))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower())


def narration(m: Merchant, rng: random.Random, when: date) -> str:
    """A statement narration in the merchant's format. Bank codes and handles are fictional."""
    ref, ifsc = _digits(rng, 12), f"FKBK0{_digits(rng, 6)}"
    month = when.strftime("%b").upper()
    remark = m.remark or "UPI"
    return {
        "upi_dr": f"UPI/DR/{ref}/{m.name}/{ifsc}/{_slug(m.name)}@fkbank/{remark}",
        "upi_cr": f"UPI/CR/{ref}/{m.name}/{ifsc}/{_slug(m.name)}@fkbank/{remark}",
        "neft_dr": f"NEFT/DR/{ref}/{m.name}/{remark} {month}",
        "neft_cr": f"NEFT/CR/FKBKN{_digits(rng, 8)}/{m.name}/{remark} {month}",
        "ach": f"ACH/{m.name}/{ref}/{remark}",
        "pos": f"POS {_digits(rng, 4)}XXXXXX{_digits(rng, 4)} {m.name}",
        "imps": f"IMPS/P2A/{ref}/{m.name}/{rng.choice(['GIFT', 'SHARE', 'PAYBACK'])}",
        "atm": f"ATM WDL/{ref}/{m.name}",
        "interest": f"BY INTEREST CREDIT/{ref}",
    }[m.fmt]


def _months() -> list[date]:
    months, current = [], FIRST_MONTH
    while current <= TODAY:
        months.append(current)
        current = date(current.year + current.month // 12, current.month % 12 + 1, 1)
    return months


def _last_day(month: date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


def _on(month: date, day: int) -> date:
    """That day of the month, or the month's last day: a "30th" lands on 28 February."""
    return month.replace(day=min(day, _last_day(month)))


def _dates(m: Merchant, rng: random.Random) -> list[date]:
    months = _months()
    kind = m.schedule[0]
    if kind == "monthly":
        days = [_on(month, m.schedule[1]) for month in months]
    elif kind == "every":
        _, step, day = m.schedule
        days = [_on(month, day) for month in months[::step]]
    else:  # occasional: different months, a random day in each
        days = [
            _on(month, rng.randint(1, _last_day(month)))
            for month in rng.sample(months, m.schedule[1])
        ]
    return [day for day in days if day <= TODAY]


def build() -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    rows = []
    for m in MERCHANTS:
        for when in _dates(m, rng):
            description = narration(m, rng, when)
            amount = Decimal(rng.randint(m.low * 100, m.high * 100)) / 100
            note = rng.choice(m.notes) if m.notes and rng.random() < 0.4 else ""
            rows.append(
                {
                    "merchant": m.key,
                    "date": when,
                    "txn_type": m.txn_type,
                    "amount": f"{amount:.2f}",
                    "category": m.category,
                    "name": clean_name(description),
                    "description": description,
                    "notes": note,
                }
            )
    rows.sort(key=lambda row: (row["date"], row["merchant"]))
    for number, row in enumerate(rows, start=1):
        row["id"] = f"t{number:03d}"

    def ids(*merchants: str, start: date = date.min, end: date = date.max) -> list[str]:
        return [
            row["id"]
            for row in rows
            if row["merchant"] in merchants and start <= row["date"] <= end
        ]

    questions = [
        # (id, question, relevant rows)
        ("gym", "What do I pay for the gym?", ids("gym")),
        ("landlord", "When did I last pay my landlord?", ids("rent")),
        ("electricity", "How much did I spend on electricity?", ids("power")),
        ("phone", "Show my mobile phone bills", ids("mobile")),
        ("internet", "What do I pay for internet?", ids("broadband")),
        ("water", "Water bill payments", ids("water")),
        ("streaming", "Which streaming subscriptions do I pay for?", ids("cinestream", "tunewave")),
        ("coffee", "How much do I spend on coffee?", ids("coffee")),
        ("salary", "When was my salary credited?", ids("salary")),
        ("petrol", "Petrol expenses", ids("fuel")),
        ("taxi", "Taxi rides", ids("cabs")),
        ("medicine", "Medicine purchases", ids("pharmacy")),
        ("doctor", "Doctor consultations", ids("clinic")),
        ("train", "Train tickets", ids("rail")),
        ("flight", "Flight bookings", ids("airline")),
        ("hotel", "Hotel stays", ids("hotel")),
        ("insurance", "Insurance premium payments", ids("insurance")),
        ("loan", "Home loan EMI", ids("emi")),
        ("tuition", "Tuition fees", ids("tutors")),
        ("clothes", "Clothes shopping", ids("apparel")),
        ("electronics", "Electronics I bought", ids("gadgets")),
        ("groceries", "Grocery shopping", ids("greenleaf", "freshbasket", "dailyneeds")),
        ("refunds", "Refunds I received", ids("refund")),
        ("friend", "Money sent to R Sample", ids("transfer")),
        ("cash", "Cash withdrawals", ids("atm")),
        ("movies", "Movie tickets", ids("cinestar")),
        ("games", "Video game purchases", ids("gamevault")),
        ("biryani", "Biryani orders", ids("biryani")),
        ("interest", "Interest earned on savings", ids("interest")),
        ("metro", "Metro card recharges", ids("metro")),
        ("breakfast", "Breakfast at Daily Dosa", ids("dosa")),
        # With a date phrase: the period comes from the question (TODAY is 2026-10-15).
        ("gym-march", "Gym payments in March 2026",
         ids("gym", start=date(2026, 3, 1), end=date(2026, 3, 31))),
        ("power-last-month", "Electricity bill last month",
         ids("power", start=date(2026, 9, 1), end=date(2026, 9, 30))),
        ("salary-this-year", "Salary this year",
         ids("salary", start=date(2026, 1, 1), end=TODAY)),
        ("fuel-3-months", "Fuel in the last 3 months",
         ids("fuel", start=date(2026, 8, 1), end=TODAY)),
        ("rent-2025", "Rent paid in 2025",
         ids("rent", start=date(2025, 1, 1), end=date(2025, 12, 31))),
    ]  # fmt: skip
    no_answer = [
        ("horse", "Horse riding lessons"),
        ("dog", "Dog grooming"),
        ("crypto", "Crypto exchange deposits"),
        ("piano", "Piano teacher"),
        ("parking", "Parking fines"),
        ("jewellery", "Jewellery"),
        ("lottery", "Lottery winnings"),
        ("vet", "Vet visits"),
    ]

    # A no-answer question must share no keyword with any row, or it isn't a no-answer question.
    vocabulary = {
        token
        for row in rows
        for token in tokenize(
            f"{prepare_text(row['name'], row['description'], row['notes'])} {row['category']}"
        )
    }
    for qid, question in no_answer:
        overlap = set(remove_stopwords(tokenize(question))) & vocabulary
        assert not overlap, f"{qid}: {overlap} appears in the corpus"
    for qid, _, relevant in questions:
        assert relevant, f"{qid} has no relevant rows"

    corpus = [
        {
            key: (value.isoformat() if isinstance(value, date) else value)
            for key, value in row.items()
        }
        for row in rows
    ]
    for row in corpus:
        del row["merchant"]  # a generation detail; the evaluation sees only what an import stores
    question_list = [
        {"id": qid, "question": question, "relevant": relevant}
        for qid, question, relevant in questions
    ] + [{"id": qid, "question": question, "relevant": []} for qid, question in no_answer]
    return corpus, question_list


def write() -> str:
    """Writes both files and returns a one-line summary."""
    corpus, questions = build()
    for filename, data in (("rag_corpus.json", corpus), ("rag_questions.json", questions)):
        text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        (HERE / filename).write_text(text, encoding="utf-8")
    answerable = sum(1 for q in questions if q["relevant"])
    return (
        f"{len(corpus)} transactions, {answerable} answerable questions, "
        f"{len(questions) - answerable} with no answer"
    )
