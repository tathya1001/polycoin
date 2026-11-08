"""Builds the retrieval evaluation sets: a dev set for tuning and a locked test set.

    docker compose exec backend python manage.py build_rag_eval

dev: rag_corpus.json and rag_questions.json. Tuning and cross-validation use only this set.
test: rag_test_corpus.json and rag_test_questions.json, built from a separate list of merchants
so tuning can't learn their names. It is written once, its fingerprint is pinned by a test, and it
is scored only for the final, held-out numbers.

Deterministic (fixed seeds), so the files only change when this script does. Every merchant, UPI
handle and bank code is made up. Narrations follow Indian bank statement formats (UPI, NEFT, IMPS,
ACH, POS, ATM), and each row's name comes from the importer's own clean_name(), so the documents
are exactly what a real import would produce.

Each question's relevant rows are derived from the merchants that generated them, so the expected
answers can't drift from the data. Every question has a type, and build() checks each type's
rule (a paraphrase shares no keyword with its rows, for example). After changing this file, run
it, then re-embed with `python manage.py embed_rag_eval`.
"""

import calendar
import json
import random
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from ai.rag.periods import detect_period
from ai.rag.retriever import remove_stopwords, tokenize
from ai.scoring import prepare_text
from insights.spec import resolve_period
from transactions.importer import clean_name

HERE = Path(__file__).parent
TODAY = date(2026, 10, 15)  # the evaluation's fixed "today"; the history ends here
FIRST_MONTH = date(2025, 11, 1)  # twelve months of history
SEED = 2026
TEST_SEED = 4242
SPLITS = ("dev", "test")

# What each question tests. The first five have relevant rows; the last two have none. Hindi typed
# in Latin letters was measured once and dropped as out of scope: no model compared handled it.
TYPES = (
    "exact",  # every relevant row shares a keyword with the question
    "paraphrase",  # no relevant row shares a keyword with the question
    "typo",  # a misspelt key word
    "multi",  # the relevant rows come from two or more merchants
    "dated",  # a date phrase sets the period
    "near-miss",  # no answer, but shares words with rows that don't answer it
    "no-answer",  # no answer, and no keyword in common with any row
)
ANSWERABLE = TYPES[:5]


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
    # Added later, at the end, so the rows above keep their random draws. Several share words
    # with older ones ("HOME", "BILL", "CARD", "SUBSCRIPTION"), as real statements do.
    Merchant("lifeline", "LIFELINE ASSURANCE", "Others", "ach", 3100, 3100, ("every", 6, 14),
             remark="LIFE COVER PREMIUM"),
    Merchant("gas", "BLUEFLAME GAS AGENCY", "Bills", "upi_dr", 850, 950, ("every", 2, 9),
             remark="LPG REFILL"),
    Merchant("dth", "STARBEAM DTH", "Bills", "upi_dr", 349, 349, ("monthly", 20),
             remark="DTH RECHARGE"),
    Merchant("dairy", "MOONBEAM DAIRY", "Groceries", "upi_dr", 900, 1400, ("monthly", 2),
             remark="MONTHLY DUES"),
    Merchant("homecare", "TIDYNEST HOME SERVICES", "Others", "upi_dr", 2500, 2500,
             ("monthly", 6), remark="HOUSE CLEANING"),
    Merchant("tea", "LEAFYCUP TEA HOUSE", "Food", "upi_dr", 60, 240, ("times", 7)),
    Merchant("delivery", "QUICKBITE DELIVERY", "Food", "upi_dr", 220, 950, ("times", 9),
             notes=("late night order",)),
    Merchant("cloud", "NIMBUS CLOUD STORAGE", "Others", "ach", 130, 130, ("monthly", 26),
             remark="SUBSCRIPTION"),
    Merchant("books", "PAGETURN BOOKSTORE", "Shopping", "pos", 300, 1500, ("times", 4),
             notes=("novels",)),
    Merchant("salon", "SNIPSHAPE SALON", "Others", "upi_dr", 400, 1800, ("times", 5)),
    Merchant("charity", "HELPING HANDS TRUST", "Others", "neft_dr", 1000, 2000, ("times", 2),
             remark="DONATION"),
    Merchant("freelance", "BRIGHTPIXEL STUDIO", "Others", "neft_cr", 8000, 25000, ("times", 3),
             txn_type="credit", remark="INVOICE PAYMENT"),
    Merchant("bus", "INTERCITY BUSLINES", "Transport", "upi_dr", 600, 1400, ("times", 3)),
    Merchant("sip", "NORTHSTAR MUTUAL FUND", "Others", "ach", 5000, 5000, ("monthly", 7),
             remark="SIP"),
    Merchant("card", "ORBIT BANK CARD", "Others", "neft_dr", 3000, 15000, ("monthly", 22),
             remark="CREDIT CARD BILL"),
]  # fmt: skip

# The locked test set's merchants: none of the names above.
TEST_MERCHANTS = [
    Merchant("rent", "OAKWOOD RESIDENCY", "Rent", "neft_dr", 18500, 18500, ("monthly", 4),
             remark="HOUSE RENT"),
    Merchant("salary", "GLOBEX SYSTEMS PAYROLL", "Salary", "neft_cr", 72000, 72000,
             ("monthly", 1), txn_type="credit", remark="SALARY"),
    Merchant("power", "SUNGRID ELECTRIC", "Bills", "ach", 700, 2200, ("monthly", 9),
             remark="POWER BILL"),
    Merchant("mobile", "PULSE TELECOM", "Bills", "upi_dr", 499, 499, ("monthly", 14),
             remark="PREPAID PACK"),
    Merchant("broadband", "SWIFTNET FIBER", "Bills", "upi_dr", 999, 999, ("every", 3, 16),
             remark="INTERNET PLAN"),
    Merchant("water", "CLEARSTREAM WATER", "Bills", "ach", 250, 500, ("every", 2, 21),
             remark="WATER BILL"),
    Merchant("gas", "HEARTH GAS", "Bills", "upi_dr", 900, 1000, ("every", 2, 11),
             remark="CYLINDER BOOKING"),
    Merchant("gym", "IRONPEAK FITNESS", "Health", "upi_dr", 2000, 2000, ("monthly", 6),
             remark="MONTHLY FEE"),
    Merchant("yoga", "LOTUS YOGA STUDIO", "Health", "upi_dr", 1200, 1200, ("monthly", 3),
             remark="CLASSES"),
    Merchant("streaming", "REELBOX", "Entertainment", "ach", 299, 299, ("monthly", 17),
             remark="SUBSCRIPTION"),
    Merchant("music", "MELODIA", "Entertainment", "upi_dr", 99, 99, ("monthly", 23),
             remark="PREMIUM"),
    Merchant("insurance", "TRUSTSHIELD HEALTH INSURANCE", "Health", "ach", 5200, 5200,
             ("every", 6, 12), remark="POLICY RENEWAL"),
    Merchant("emi", "CAPSTONE AUTO LOANS", "Others", "ach", 9800, 9800, ("monthly", 5),
             remark="CAR LOAN EMI"),
    Merchant("school", "LITTLE SPROUTS SCHOOL", "Others", "neft_dr", 15000, 15000,
             ("every", 3, 8), remark="TERM FEES"),
    Merchant("interest", "INTEREST CREDIT", "Others", "interest", 150, 380, ("every", 3, 28),
             txn_type="credit"),
    Merchant("cafe", "MORNING MUG CAFE", "Food", "upi_dr", 120, 480, ("times", 9)),
    Merchant("pizza", "CRUSTWORKS PIZZA", "Food", "upi_dr", 350, 1200, ("times", 6),
             notes=("friday night",)),
    Merchant("thali", "SAFFRON THALI HOUSE", "Food", "pos", 180, 420, ("times", 6)),
    Merchant("juice", "SQUEEZE JUICE BAR", "Food", "upi_dr", 80, 250, ("times", 5)),
    Merchant("bakery", "GOLDENCRUST BAKERY", "Food", "pos", 90, 400, ("times", 5)),
    Merchant("supermarket", "VALUECART SUPERMARKET", "Groceries", "pos", 800, 4200,
             ("times", 9)),
    Merchant("provisions", "CORNERSTOP PROVISIONS", "Groceries", "upi_dr", 150, 1100,
             ("times", 7)),
    Merchant("autos", "ZIPAUTO RIDES", "Transport", "upi_dr", 60, 300, ("times", 9)),
    Merchant("fuel", "HIGHWAY FUELS", "Transport", "pos", 800, 2800, ("times", 9)),
    Merchant("train", "TRACKLINE RAIL", "Transport", "upi_dr", 300, 1900, ("times", 3)),
    Merchant("flights", "BLUEWING AIR", "Transport", "upi_dr", 3800, 8800, ("times", 2)),
    Merchant("resort", "PALM COVE RESORT", "Others", "upi_dr", 6000, 14000, ("times", 1)),
    Merchant("fashion", "URBAN THREADS", "Shopping", "pos", 700, 3800, ("times", 4),
             notes=("shoes",)),
    Merchant("electronics", "VOLTEDGE DIGITAL", "Shopping", "upi_dr", 1800, 26000, ("times", 2),
             notes=("phone case", "earbuds")),
    Merchant("decor", "NESTWELL HOME DECOR", "Shopping", "upi_dr", 600, 5000, ("times", 3)),
    Merchant("cinema", "GRANDVIEW CINEMAS", "Entertainment", "upi_dr", 250, 800, ("times", 4)),
    Merchant("concerts", "LIVEWIRE EVENTS", "Entertainment", "upi_dr", 1500, 3500,
             ("times", 2), remark="CONCERT"),
    Merchant("pharmacy", "MEDIPLUS CHEMIST", "Health", "pos", 120, 1500, ("times", 5)),
    Merchant("dentist", "BRIGHTSMILE DENTAL", "Health", "upi_dr", 800, 4500, ("times", 2)),
    Merchant("vet", "PAWS AND CLAWS VET", "Others", "upi_dr", 600, 2500, ("times", 2)),
    Merchant("transfer", "K EXAMPLE", "Transfer", "imps", 500, 6000, ("times", 4),
             notes=("rent share",)),
    Merchant("atm", "LINK ROAD BRANCH", "Others", "atm", 1000, 8000, ("times", 4)),
    Merchant("refund", "VALUECART SUPERMARKET", "Groceries", "upi_cr", 200, 1500, ("times", 2),
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


def _rows(merchants: list[Merchant], seed: int, prefix: str) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for m in merchants:
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
        row["id"] = f"{prefix}{number:03d}"
    return rows


class _Rows:
    """Looks up row ids by merchant and period."""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def ids(self, *merchants: str, start: date = date.min, end: date = date.max) -> list[str]:
        return [
            row["id"]
            for row in self.rows
            if row["merchant"] in merchants and start <= row["date"] <= end
        ]

    def dated(self, question: str, *merchants: str) -> list[str]:
        """The merchants' rows in the period the question's date phrase names."""
        detected = detect_period(question, TODAY)
        start, end = resolve_period(detected.date_filter, detected.date_filter, TODAY)
        return self.ids(*merchants, start=start, end=end)


def _dev_questions(r: _Rows) -> list[tuple]:
    """(id, type, question, relevant rows)."""
    return [
        # Exact: the question uses a word from its rows.
        ("gym", "exact", "What do I pay for the gym?", r.ids("gym")),
        ("electricity", "exact", "How much did I spend on electricity?", r.ids("power")),
        ("phone", "exact", "Show my mobile phone bills", r.ids("mobile")),
        ("water", "exact", "Water bill payments", r.ids("water")),
        ("coffee", "exact", "How much do I spend on coffee?", r.ids("coffee")),
        ("salary", "exact", "When was my salary credited?", r.ids("salary")),
        ("petrol", "exact", "Petrol expenses", r.ids("fuel")),
        ("loan", "exact", "Home loan EMI", r.ids("emi")),
        ("tuition", "exact", "Tuition fees", r.ids("tutors")),
        ("clothes", "exact", "Clothes shopping", r.ids("apparel")),
        ("electronics", "exact", "Electronics I bought", r.ids("gadgets")),
        ("refunds", "exact", "Refunds I received", r.ids("refund")),
        ("friend", "exact", "Money sent to R Sample", r.ids("transfer")),
        ("biryani", "exact", "Biryani orders", r.ids("biryani")),
        ("interest", "exact", "Interest earned on savings", r.ids("interest")),
        ("metro", "exact", "Metro card recharges", r.ids("metro")),
        ("breakfast", "exact", "Breakfast at Daily Dosa", r.ids("dosa")),
        ("hotel", "exact", "Hotel stays", r.ids("hotel")),
        ("train", "exact", "Train tickets", r.ids("rail")),
        ("doctor", "exact", "Doctor consultations", r.ids("clinic")),
        ("gas", "exact", "Cooking gas refills", r.ids("gas")),
        ("dth", "exact", "DTH recharge", r.ids("dth")),
        ("dairy", "exact", "Milk from Moonbeam Dairy", r.ids("dairy")),
        ("cleaning", "exact", "House cleaning service", r.ids("homecare")),
        ("life-cover", "exact", "Life cover premium", r.ids("lifeline")),
        ("quickbite", "exact", "Quickbite delivery orders", r.ids("delivery")),
        ("cloud", "exact", "Cloud storage plan", r.ids("cloud")),
        ("pageturn", "exact", "Books from Pageturn", r.ids("books")),
        ("salon", "exact", "Salon visits", r.ids("salon")),
        ("sip", "exact", "Mutual fund SIP", r.ids("sip")),
        ("card-bill", "exact", "Credit card bill payments", r.ids("card")),
        ("donations", "exact", "Donations to Helping Hands Trust", r.ids("charity")),
        ("intercity", "exact", "Intercity bus tickets", r.ids("bus")),
        ("invoices", "exact", "Invoice payments from Brightpixel Studio", r.ids("freelance")),
        # Paraphrase: no keyword in common, so only the vectors can find these.
        ("landlord", "paraphrase", "When did I last pay my landlord?", r.ids("rent")),
        ("internet", "paraphrase", "What do I pay for internet?", r.ids("broadband")),
        ("cash", "paraphrase", "Cash withdrawals", r.ids("atm")),
        ("movies", "paraphrase", "Movie tickets", r.ids("cinestar")),
        ("games", "paraphrase", "Video game purchases", r.ids("gamevault")),
        ("flight", "paraphrase", "Flight bookings", r.ids("airline")),
        ("medicine", "paraphrase", "Medicine purchases", r.ids("pharmacy")),
        ("taxi", "paraphrase", "Taxi rides", r.ids("cabs")),
        ("lights", "paraphrase", "Keeping the lights on", r.ids("power")),
        ("fit", "paraphrase", "Staying fit", r.ids("gym")),
        ("mortgage", "paraphrase", "Mortgage repayments", r.ids("emi")),
        ("education", "paraphrase", "Kids' education costs", r.ids("tutors")),
        ("songs", "paraphrase", "Songs I listen to", r.ids("tunewave")),
        ("employer", "paraphrase", "Money from my employer", r.ids("salary")),
        ("physician", "paraphrase", "Seeing a physician", r.ids("clinic")),
        ("films", "paraphrase", "Watching films at the theatre", r.ids("cinestar")),
        ("air-travel", "paraphrase", "Air travel", r.ids("airline")),
        ("trips", "paraphrase", "Where I stayed on trips", r.ids("hotel")),
        ("wifi", "paraphrase", "Wi-Fi charges", r.ids("broadband")),
        ("telly", "paraphrase", "Telly channels", r.ids("dth")),
        ("fresh-milk", "paraphrase", "Fresh milk", r.ids("dairy")),
        ("maid", "paraphrase", "Maid and housekeeping", r.ids("homecare")),
        ("takeaway", "paraphrase", "Takeaway apps", r.ids("delivery")),
        ("photos", "paraphrase", "Photos backup", r.ids("cloud")),
        ("reading", "paraphrase", "Reading material", r.ids("books")),
        ("haircuts", "paraphrase", "Haircuts", r.ids("salon")),
        ("investments", "paraphrase", "Monthly investments", r.ids("sip")),
        ("charity", "paraphrase", "Charity", r.ids("charity")),
        ("freelance", "paraphrase", "Freelance income", r.ids("freelance")),
        ("coach", "paraphrase", "Coach travel between cities", r.ids("bus")),
        # Typo: a misspelt key word.
        ("typo-electricity", "typo", "electricty bill", r.ids("power")),
        ("typo-gym", "typo", "gym memebership", r.ids("gym")),
        ("typo-groceries", "typo", "grocerys",
         r.ids("greenleaf", "freshbasket", "dailyneeds", "dairy")),
        ("typo-petrol", "typo", "petrol expences", r.ids("fuel")),
        ("typo-insurance", "typo", "insurence premium", r.ids("insurance", "lifeline")),
        ("typo-pharmacy", "typo", "phramacy", r.ids("pharmacy")),
        ("typo-subscriptions", "typo", "subscritpions", r.ids("cinestream", "tunewave", "cloud")),
        ("typo-tuition", "typo", "tution fees", r.ids("tutors")),
        ("typo-salary", "typo", "salry credited", r.ids("salary")),
        ("typo-biryani", "typo", "biriyani", r.ids("biryani")),
        ("typo-coffee", "typo", "cofee", r.ids("coffee")),
        ("typo-water", "typo", "watter bill", r.ids("water")),
        ("typo-hotel", "typo", "hotle bookings", r.ids("hotel")),
        ("typo-movies", "typo", "moive tickets", r.ids("cinestar")),
        ("typo-interest", "typo", "intrest earned", r.ids("interest")),
        # Multi: two or more merchants, sometimes a whole category.
        ("streaming", "multi", "Which streaming subscriptions do I pay for?",
         r.ids("cinestream", "tunewave")),
        ("insurance", "multi", "Insurance premium payments", r.ids("insurance", "lifeline")),
        ("groceries", "multi", "Grocery shopping",
         r.ids("greenleaf", "freshbasket", "dailyneeds", "dairy")),
        ("subscriptions", "multi", "All my subscriptions",
         r.ids("cinestream", "tunewave", "cloud")),
        ("utilities", "multi", "Utility bills", r.ids("power", "water", "gas")),
        ("travel", "multi", "Flights, trains and hotels", r.ids("airline", "rail", "hotel")),
        ("transport", "multi", "Transport costs",
         r.ids("cabs", "fuel", "metro", "rail", "airline", "bus")),
        ("health", "multi", "Health spending", r.ids("gym", "insurance", "pharmacy", "clinic")),
        ("entertainment", "multi", "Entertainment expenses",
         r.ids("cinestream", "tunewave", "cinestar", "gamevault")),
        ("shopping", "multi", "Shopping expenses",
         r.ids("brightmart", "apparel", "gadgets", "books")),
        ("brightmart-all", "multi", "Everything at Brightmart", r.ids("brightmart", "refund")),
        ("housing", "multi", "Rent and home loan EMI", r.ids("rent", "emi")),
        ("medical", "multi", "Doctor and medicine costs", r.ids("clinic", "pharmacy")),
        ("commute", "multi", "Cab and metro rides", r.ids("cabs", "metro")),
        ("hot-drinks", "multi", "Tea and coffee", r.ids("tea", "coffee")),
        # Dated: the period comes from the question (TODAY is 2026-10-15).
        ("gym-march", "dated", "Gym payments in March 2026",
         r.ids("gym", start=date(2026, 3, 1), end=date(2026, 3, 31))),
        ("power-last-month", "dated", "Electricity bill last month",
         r.ids("power", start=date(2026, 9, 1), end=date(2026, 9, 30))),
        ("salary-this-year", "dated", "Salary this year",
         r.ids("salary", start=date(2026, 1, 1), end=TODAY)),
        ("fuel-3-months", "dated", "Fuel in the last 3 months",
         r.ids("fuel", start=date(2026, 8, 1), end=TODAY)),
        ("rent-2025", "dated", "Rent paid in 2025",
         r.ids("rent", start=date(2025, 1, 1), end=date(2025, 12, 31))),
        ("mobile-august", "dated", "Mobile bill in August 2026",
         r.dated("Mobile bill in August 2026", "mobile")),
        ("sip-last-month", "dated", "SIP last month", r.dated("SIP last month", "sip")),
        ("milk-this-month", "dated", "Milk this month", r.dated("Milk this month", "dairy")),
        ("rent-2026", "dated", "Rent in 2026", r.dated("Rent in 2026", "rent")),
        ("card-3-months", "dated", "Credit card bill last 3 months",
         r.dated("Credit card bill last 3 months", "card")),
        ("cloud-past-year", "dated", "Cloud storage in the past year",
         r.dated("Cloud storage in the past year", "cloud")),
        ("cleaning-december", "dated", "Home cleaning in December 2025",
         r.dated("Home cleaning in December 2025", "homecare")),
        ("gas-this-year", "dated", "Gas refills this year",
         r.dated("Gas refills this year", "gas")),
        ("emi-last-year", "dated", "EMI last year", r.dated("EMI last year", "emi")),
        ("water-may", "dated", "Water bill during May", r.dated("Water bill during May", "water")),
        # Near-miss: no answer, but words in common with rows that don't answer it.
        ("car-insurance", "near-miss", "Car insurance", []),
        ("power-refund", "near-miss", "Electricity bill refund", []),
        ("phone-purchase", "near-miss", "Mobile phone purchase", []),
        ("home-insurance", "near-miss", "Home insurance", []),
        ("coffee-machine", "near-miss", "Coffee machine", []),
        ("rent-received", "near-miss", "Rent received from my tenant", []),
        ("gym-equipment", "near-miss", "Gym equipment", []),
        ("water-purifier", "near-miss", "Water purifier service", []),
        ("flight-refund", "near-miss", "Flight cancellation refund", []),
        ("tuition-refund", "near-miss", "Tuition fees refund", []),
        ("petrol-cashback", "near-miss", "Petrol pump cashback", []),
        ("salary-bonus", "near-miss", "Salary bonus", []),
        ("ticket-cancellation", "near-miss", "Ticket cancellation charges", []),
        ("gas-deposit", "near-miss", "Gas cylinder deposit refund", []),
        ("insurance-claim", "near-miss", "Life insurance claim payout", []),
        # No answer: nothing in common with any row.
        ("horse", "no-answer", "Horse riding lessons", []),
        ("dog", "no-answer", "Dog grooming", []),
        ("crypto", "no-answer", "Crypto exchange deposits", []),
        ("piano", "no-answer", "Piano teacher", []),
        ("parking", "no-answer", "Parking fines", []),
        ("jewellery", "no-answer", "Jewellery", []),
        ("lottery", "no-answer", "Lottery winnings", []),
        ("vet", "no-answer", "Vet visits", []),
        ("swimming", "no-answer", "Swimming classes", []),
        ("boat", "no-answer", "Boat rental", []),
    ]  # fmt: skip


def _test_questions(r: _Rows) -> list[tuple]:
    """The locked test set's questions: the same types, about 40% as many."""
    return [
        ("rent", "exact", "How much rent did I pay?", r.ids("rent")),
        ("salary", "exact", "Salary credits", r.ids("salary")),
        ("power", "exact", "Power bill payments", r.ids("power")),
        ("yoga", "exact", "Yoga studio fees", r.ids("yoga")),
        ("insurance", "exact", "Health insurance renewal", r.ids("insurance")),
        ("car-loan", "exact", "Car loan EMI", r.ids("emi")),
        ("pizza", "exact", "Pizza orders", r.ids("pizza")),
        ("supermarket", "exact", "Supermarket shopping", r.ids("supermarket")),
        ("fuel", "exact", "Highway Fuels payments", r.ids("fuel")),
        ("cinema", "exact", "Cinema tickets", r.ids("cinema")),
        ("dentist", "exact", "Dental visits", r.ids("dentist")),
        ("concert", "exact", "Concert tickets", r.ids("concerts")),
        ("juice", "exact", "Juice bar", r.ids("juice")),
        ("landlord", "paraphrase", "Payments to my landlord", r.ids("rent")),
        ("paycheck", "paraphrase", "Paychecks from work", r.ids("salary")),
        ("wifi", "paraphrase", "Wi-Fi connection", r.ids("broadband")),
        ("cellphone", "paraphrase", "Cellphone top-ups", r.ids("mobile")),
        ("workout", "paraphrase", "Working out", r.ids("gym")),
        ("meditation", "paraphrase", "Meditation and stretching sessions", r.ids("yoga")),
        ("shows", "paraphrase", "TV shows and series", r.ids("streaming")),
        ("schooling", "paraphrase", "Kids' schooling", r.ids("school")),
        ("pills", "paraphrase", "Pills and prescriptions", r.ids("pharmacy")),
        ("three-wheeler", "paraphrase", "Three-wheeler trips", r.ids("autos")),
        ("holiday", "paraphrase", "Beach holiday stay", r.ids("resort")),
        ("pet", "paraphrase", "Pet doctor", r.ids("vet")),
        ("typo-yoga", "typo", "yoga studoi", r.ids("yoga")),
        ("typo-electricity", "typo", "electrcity bill", r.ids("power")),
        ("typo-supermarket", "typo", "supermaket", r.ids("supermarket")),
        ("typo-insurance", "typo", "insurace renewal", r.ids("insurance")),
        ("typo-pizza", "typo", "pizaa orders", r.ids("pizza")),
        ("typo-concert", "typo", "concret tickets", r.ids("concerts")),
        ("subscriptions", "multi", "Streaming and music subscriptions",
         r.ids("streaming", "music")),
        ("fitness", "multi", "Gym and yoga", r.ids("gym", "yoga")),
        ("utilities", "multi", "Utility bills", r.ids("power", "water", "gas")),
        ("food", "multi", "Food spending", r.ids("cafe", "pizza", "thali", "juice", "bakery")),
        ("travel", "multi", "Trains and flights", r.ids("train", "flights")),
        ("health", "multi", "Health spending",
         r.ids("gym", "yoga", "insurance", "pharmacy", "dentist")),
        ("rent-last-month", "dated", "Rent last month", r.dated("Rent last month", "rent")),
        ("salary-march", "dated", "Salary in March 2026",
         r.dated("Salary in March 2026", "salary")),
        ("yoga-this-year", "dated", "Yoga this year", r.dated("Yoga this year", "yoga")),
        ("mobile-3-months", "dated", "Mobile pack in the last 3 months",
         r.dated("Mobile pack in the last 3 months", "mobile")),
        ("emi-2025", "dated", "Car loan EMI in 2025", r.dated("Car loan EMI in 2025", "emi")),
        ("gym-this-month", "dated", "Gym fee this month", r.dated("Gym fee this month", "gym")),
        ("car-insurance", "near-miss", "Car insurance", []),
        ("pizza-oven", "near-miss", "Pizza oven", []),
        ("yoga-mat", "near-miss", "Yoga mat purchase", []),
        ("power-deposit", "near-miss", "Electricity deposit refund", []),
        ("school-bus", "near-miss", "School bus fees", []),
        ("concert-refund", "near-miss", "Concert refund", []),
        ("skydiving", "no-answer", "Skydiving", []),
        ("tattoo", "no-answer", "Tattoo parlour", []),
        ("guitar", "no-answer", "Guitar strings", []),
        ("lottery", "no-answer", "Lottery tickets", []),
        ("knitting", "no-answer", "Knitting wool", []),
    ]  # fmt: skip


def _row_tokens(row: dict) -> set[str]:
    """The keywords search sees for a row: its text and its category name."""
    text = prepare_text(row["name"], row["description"], row["notes"])
    return set(tokenize(f"{text} {row['category']}"))


def _check(rows: list[dict], questions: list[tuple]) -> None:
    """Every question must follow its type's rule, or it doesn't test what its type says."""
    tokens = {row["id"]: _row_tokens(row) for row in rows}
    merchant = {row["id"]: row["merchant"] for row in rows}
    vocabulary = set().union(*tokens.values())
    seen = set()
    for qid, kind, question, relevant in questions:
        assert qid not in seen, f"{qid} is used twice"
        seen.add(qid)
        assert kind in TYPES, f"{qid}: unknown type {kind}"
        detected = detect_period(question, TODAY)
        assert (detected is not None) == (kind == "dated"), f"{qid}: date phrase vs type"
        words = set(remove_stopwords(tokenize(detected.remainder if detected else question)))
        if kind in ANSWERABLE:
            assert relevant, f"{qid} has no relevant rows"
            assert len(relevant) <= settings.RAG_MAX_MATCHES, f"{qid}: more rows than search keeps"
        else:
            assert not relevant, f"{qid} is a no-answer question with relevant rows"
        if kind == "exact":
            missing = [row for row in relevant if not words & tokens[row]]
            assert not missing, f"{qid}: {missing} share no keyword with the question"
        elif kind == "paraphrase":
            shared = {row: words & tokens[row] for row in relevant if words & tokens[row]}
            assert not shared, f"{qid}: shares keywords {shared}"
        elif kind == "multi":
            assert len({merchant[row] for row in relevant}) >= 2, f"{qid}: one merchant"
        elif kind == "near-miss":
            assert words & vocabulary, f"{qid} shares no keyword with the corpus"
        elif kind == "no-answer":
            overlap = words & vocabulary
            assert not overlap, f"{qid}: {overlap} appears in the corpus"


def build(split: str = "dev") -> tuple[list[dict], list[dict]]:
    if split == "dev":
        rows, questions = _rows(MERCHANTS, SEED, "t"), _dev_questions
    elif split == "test":
        rows, questions = _rows(TEST_MERCHANTS, TEST_SEED, "h"), _test_questions
    else:
        raise ValueError(f"split is one of {SPLITS}")
    question_rows = questions(_Rows(rows))
    _check(rows, question_rows)

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
        {"id": qid, "type": kind, "question": question, "relevant": relevant}
        for qid, kind, question, relevant in question_rows
    ]
    return corpus, question_list


def write() -> str:
    """Writes both splits and returns a summary."""
    lines = []
    for split in SPLITS:
        corpus, questions = build(split)
        prefix = "rag" if split == "dev" else "rag_test"
        for name, data in (("corpus", corpus), ("questions", questions)):
            text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
            (HERE / f"{prefix}_{name}.json").write_text(text, encoding="utf-8")
        counts = ", ".join(
            f"{kind} {sum(1 for q in questions if q['type'] == kind)}" for kind in TYPES
        )
        lines.append(f"{split}: {len(corpus)} transactions, {len(questions)} questions ({counts})")
    return "\n".join(lines)
