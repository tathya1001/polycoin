"""Chart colours for categories.

Every category owns one colour: it is that category's default in every chart, and a chart
can override it for itself. Keep CATEGORY_COLORS in step with frontend/lib/colors.ts
(slots 1-8 are the dataviz palette validated for colour-blind separation; 9-12 are extras).
"""

import re
from collections.abc import Iterable

CATEGORY_COLORS = (
    "#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300",
    "#6250D6", "#E34948", "#0E9FB5", "#8D6E63", "#84A912", "#5B6B7F",
)  # fmt: skip
OTHERS_COLOR = "#9CA3AF"  # the default category is deliberately neutral grey

HEX_COLOR = re.compile(r"^#[0-9A-F]{6}$")  # upper case only: normalise before validating


def is_hex_color(value) -> bool:
    return isinstance(value, str) and HEX_COLOR.fullmatch(value) is not None


def next_color(used: Iterable[str]) -> str:
    """The first palette colour the user is not using yet; once all are used, cycle on."""
    taken = [c.upper() for c in used]
    for color in CATEGORY_COLORS:
        if color not in taken:
            return color
    return CATEGORY_COLORS[len(taken) % len(CATEGORY_COLORS)]
