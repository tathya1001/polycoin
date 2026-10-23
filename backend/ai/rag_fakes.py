"""Fictional data for the RAG performance test and memory script. Never imported by the app.

All merchant names are made up, never real companies.
"""

import random

import numpy as np

DIMS = 768  # nomic-embed-text's vector size

_PARTS = [
    "tasty", "north", "wind", "fit", "zone", "green", "leaf", "sun", "rise", "maple", "cinder",
    "river", "stone", "bright", "kite", "lumen", "oak", "pixel", "quill", "ruby", "sage", "tide",
    "cobalt", "ember", "fern", "glade", "harbor", "iris", "juniper", "koru",
]  # fmt: skip
_KINDS = [
    "Cafe", "Kitchen", "Mart", "Grocers", "Cabs", "Fuels", "Pharmacy", "Clinic", "Gym", "Studio",
    "Books", "Apparel", "Electronics", "Travels", "Stays", "Power", "Mobile", "Fibre", "Insurance",
    "Tutors",
]  # fmt: skip
_CHANNELS = ["UPI", "NEFT", "IMPS", "POS", "ATM", "ACH", "NACH", "CARD"]
_NOTES = [
    "lunch", "dinner", "monthly", "rent", "refund", "gift", "fees", "subscription", "trip",
    "groceries", "fuel", "medicines", "recharge", "emi", "bill", "weekend", "office", "family",
    "birthday", "membership", "deposit", "advance", "repair", "tickets",
]  # fmt: skip

_rng = random.Random(7)
# About 400 merchants: a realistic vocabulary for BM25, which scales with distinct tokens per row.
MERCHANTS = sorted(
    {
        f"{_rng.choice(_PARTS).title()}{_rng.choice(_PARTS)} {_rng.choice(_KINDS)}"
        for _ in range(450)
    }
)


def fake_text(rng: random.Random) -> str:
    """Shaped like prepare_text() output: merchant, channel, UPI handle, sometimes a note."""
    merchant = rng.choice(MERCHANTS)
    words = [merchant, rng.choice(_CHANNELS), merchant.split()[0].lower()]
    words += rng.sample(_NOTES, rng.choice([0, 0, 1, 2, 3]))
    return " ".join(words)


def fake_question(rng: random.Random) -> str:
    merchant = rng.choice(MERCHANTS)
    return rng.choice(
        [
            f"How much did I spend at {merchant}?",
            f"When did I last pay {merchant}?",
            f"Show my {rng.choice(_NOTES)} payments",
            f"What did I pay for {rng.choice(_NOTES)} and {rng.choice(_NOTES)}?",
        ]
    )


def unit_vectors(rng: np.random.Generator, count: int, dims: int = DIMS) -> np.ndarray:
    """Random float16 vectors of length 1, like the ones store_vectors keeps."""
    vectors = rng.standard_normal((count, dims), dtype=np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors.astype(np.float16)
