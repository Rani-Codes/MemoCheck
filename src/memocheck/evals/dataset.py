"""
Test case loading helpers.

Loads `TestCase` objects from `data/transcripts/*.json` and the held-out ID
gate from `data/held_out_ids.txt`. The runner uses these to filter the
visible-24 batch for v0 per ADR-004.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from memocheck.evals.schema import TestCase

Slice = Literal["visible", "held_out", "all"]


def load_held_out_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ids.add(line)
    return ids


def load_test_cases(transcripts_dir: Path) -> list[TestCase]:
    paths = sorted(transcripts_dir.glob("*.json"))
    return [TestCase.model_validate_json(p.read_text()) for p in paths]


def filter_slice(
    cases: list[TestCase], held_out_ids: set[str], slice: Slice
) -> list[TestCase]:
    """Filter cases by held-out membership per ADR-004 ordering.

      "visible"  -> exclude held-out (v0 / failure analysis / v1 design)
      "held_out" -> include only held-out (close-the-matrix runs)
      "all"      -> everything (final v1 run + final v0 close-out + reporting)
    """
    if slice == "all":
        return list(cases)
    if slice == "visible":
        return [c for c in cases if c.id not in held_out_ids]
    if slice == "held_out":
        return [c for c in cases if c.id in held_out_ids]
    raise ValueError(f"unknown slice {slice!r}")
