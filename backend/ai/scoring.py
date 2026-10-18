import re

from transactions.importer import _IFSC, _NOISE_WORDS, _REFERENCE_LIKE

# The vector maths (normalize, prototypes, decide) runs in the browser: frontend/lib/scoring.ts,
# held to this project's original Python outputs by lib/__fixtures__/scoring-cases.json.

# Some banks start narrations with "TO TRANSFER-" / "BY TRANSFER-". It is a bank prefix, not the
# user's words, and left in it makes every such row look like the "Transfer" category.
_TRANSFER_PREFIX = re.compile(r"(?i)^\s*(?:to|by)\s+transfer\s*-?\s*")


def prepare_text(name: str, description: str, notes: str = "") -> str:
    """The string we embed: name, the user's own notes, and a noise-stripped narration.

    'UPI/DR/412345678901/TASTYBITES/TSTB0000001/tastybites@tstb' is mostly reference numbers and
    bank codes. Left in, they drag every transaction's vector toward every other. A UPI
    handle keeps the part before the '@' (often the only place the merchant appears).
    Notes come before the narration so the length cap trims bank noise, not the user's words.
    """
    description = _TRANSFER_PREFIX.sub("", description)
    text = _IFSC.sub(" ", f"{name} {notes} {description}")
    tokens, seen = [], set()
    for token in re.split(r"[/*\s\-]+", text):
        token = token.split("@", 1)[0]  # 'tastybites@tstb' -> 'tastybites'; the bank after @ is noise
        lowered = token.lower()
        if not token or lowered in seen or lowered in _NOISE_WORDS:
            continue
        if token.isdigit():
            continue
        if len(token) >= 6 and _REFERENCE_LIKE.fullmatch(token):
            continue
        seen.add(lowered)
        tokens.append(token)
    return " ".join(tokens)[:300] or name
