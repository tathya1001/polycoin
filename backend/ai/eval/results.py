"""Saved evaluation runs: one JSON file per run in ai/eval/results/, which git ignores.

Each file says what produced its numbers (date, commit, model and digest, prompt version, dataset
fingerprint), so every number in a report can be traced back. A saved run is also the "before"
that a later change is compared with, question by question.
"""

import json
import os
import re
from datetime import date, datetime
from pathlib import Path

RESULTS = Path(__file__).parent / "results"
_LABEL = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")


def metadata(**extra) -> dict:
    """Date and commit, plus whatever the run adds. The container has no .git folder, so the
    commit comes from GIT_COMMIT (`git describe --always --dirty` on the host)."""
    return {
        "date": date.today().isoformat(),
        "commit": os.environ.get("GIT_COMMIT", "unknown"),
        **extra,
    }


def path_for(kind: str, label: str) -> Path:
    if not _LABEL.fullmatch(label):
        raise ValueError("A label is lower-case letters, digits and hyphens, like 'baseline'.")
    return RESULTS / f"{kind}-{label}.json"


def save(kind: str, label: str, payload: dict, overwrite: bool = False) -> Path:
    path = path_for(kind, label)
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path.name} exists. Pick another label, or pass --overwrite.")
    RESULTS.mkdir(exist_ok=True)
    saved = datetime.now().isoformat(timespec="seconds")
    record = {"kind": kind, "label": label, "saved": saved, **payload}
    path.write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def load_all(kind: str) -> list[dict]:
    """Every saved run of one kind, oldest first."""
    if not RESULTS.exists():
        return []
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in RESULTS.glob(f"{kind}-*.json")]
    return sorted(runs, key=lambda run: (run.get("saved") or run["meta"]["date"], run["label"]))


def load(kind: str, label: str) -> dict:
    path = path_for(kind, label)
    if not path.exists():
        raise FileNotFoundError(f"No saved run {path.name}. Save one with --record {label}.")
    return json.loads(path.read_text(encoding="utf-8"))
