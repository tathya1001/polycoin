"""Starter dashboards a user can create in one click. Pure data: every panel is an ordinary
spec, validated like any other when the template is used, so a template can't drift out of
step with the rules."""


def _panel(title: str, grid: tuple[int, int, int, int], **config) -> dict:
    """`grid` is (x, y, w, h). It's one tuple, not four keyword arguments, because the
    config has its own `x` and `y` keys (the chart axes)."""
    x, y, w, h = grid
    return {"title": title, "x": x, "y": y, "w": w, "h": h, "config": config}


OVERVIEW = [
    _panel("Spend", (0, 0, 4, 3), chart="kpi", y={"measure": "spend"}, kpi={"compare": "previous"}),
    _panel("Income", (4, 0, 4, 3), chart="kpi", y={"measure": "income"}, kpi={"compare": "previous"}),
    _panel("Net", (8, 0, 4, 3), chart="kpi", y={"measure": "net"}, kpi={"compare": "previous"}),
    _panel(
        "Spend by category", (0, 3, 6, 8),
        chart="bar", x={"field": "category"}, y={"measure": "spend"}, orientation="horizontal",
    ),
    _panel(
        "Spend share", (6, 3, 6, 8),
        chart="pie", x={"field": "category"}, y={"measure": "spend"},
    ),
    _panel(
        "Money in and out, by month", (0, 11, 12, 8),
        chart="bar", x={"field": "date", "granularity": "month"}, y={"measure": "amount"},
        color={"field": "txn_type"},
    ),
    _panel("How big are my spends?", (0, 19, 12, 7), chart="histogram", y={"measure": "spend"}),
]  # fmt: skip

TEMPLATES = {"overview": OVERVIEW}
