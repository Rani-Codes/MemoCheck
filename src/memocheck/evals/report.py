"""
v0 -> v1 comparison report (CLI `memocheck report`, step 9).

Pure aggregation + paired-bootstrap core over the per-case counts persisted in
Postgres. Micro-averaged (SUM(numerator)/SUM(denominator)) so cases with
different denominators are weighted correctly (per CLAUDE.md). The DB loader is
a thin layer on top; everything interesting here is pure and unit-testable.
"""
from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

_CASE_ID = re.compile(r"^(?:memo|synth)_\d+$")


def parse_categories(markdown_text: str) -> dict[str, str]:
    """Map case_id -> category from the `docs/test-set-composition.md` per-case
    table (the canonical, machine-omitted categorization).

    Only rows whose first cell is a case id (memo_NNN / synth_NNN) are taken, so
    the separate "Category counts" table (whose first cell is a category name)
    is ignored without needing to know table boundaries.
    """
    cats: dict[str, str] = {}
    for line in markdown_text.splitlines():
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and _CASE_ID.match(cells[0]):
            cats[cells[0]] = cells[2]
    return cats


def micro_average(pairs: Iterable[tuple[int, int]]) -> float | None:
    """Micro-average a set of (numerator, denominator) counts.

    Returns SUM(num)/SUM(den), or None when the pooled denominator is 0
    (the metric is undefined for this set, e.g. an empty pool).
    """
    num = 0
    den = 0
    for n, d in pairs:
        num += n
        den += d
    return num / den if den else None


def responded(error_message: str | None) -> bool:
    """Did the model actually return a response for this run?

    Schema Adherence is computed from `test_runs.schema_valid` over runs where
    the model responded, excluding network/infra failures (rate limit, timeout,
    connection) which never produced output (per CLAUDE.md / the standing
    decision). A clean run (no error) or a Pydantic validation failure both mean
    the model responded; the latter is a real schema miss and stays in the
    denominator. Anything else is treated as infra noise and excluded.
    """
    if error_message is None:
        return True
    return "validation error" in error_message.casefold()


@dataclass(frozen=True)
class DeltaResult:
    """One v0 -> v1 comparison: point scores, the delta, and its bootstrap CI.

    Any field is None when the metric is undefined for this set of cases (the
    pooled denominator is 0, e.g. a slice with no items of this metric's kind).
    """

    v0: float | None
    v1: float | None
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    n_cases: int


def bootstrap_delta_ci(
    v0_by_case: Mapping[str, tuple[int, int]],
    v1_by_case: Mapping[str, tuple[int, int]],
    case_ids: Sequence[str],
    *,
    n_resamples: int = 1000,
    seed: int = 0,
    ci: float = 0.95,
) -> DeltaResult:
    """Paired bootstrap CI for the v1 - v0 micro-average delta (ADR-005).

    `v0_by_case` / `v1_by_case` map case_id -> (numerator, denominator) already
    pooled across providers and attempts. The comparison is paired: the same
    resampled case_ids index both versions every iteration, preserving the
    case-level pairing. A resample whose pooled denominator is 0 on either side
    is skipped (its delta is undefined). The CI is the [2.5, 97.5] percentiles
    of the resampled deltas. Deterministic for a fixed `seed`.
    """
    point_v0 = micro_average(v0_by_case[c] for c in case_ids)
    point_v1 = micro_average(v1_by_case[c] for c in case_ids)
    point_delta = (
        point_v1 - point_v0
        if point_v0 is not None and point_v1 is not None
        else None
    )

    ci_low: float | None = None
    ci_high: float | None = None
    if point_delta is not None and case_ids:
        rng = np.random.default_rng(seed)
        n = len(case_ids)
        deltas: list[float] = []
        for _ in range(n_resamples):
            idx = rng.integers(0, n, n)
            sampled = [case_ids[i] for i in idx]
            mv0 = micro_average(v0_by_case[c] for c in sampled)
            mv1 = micro_average(v1_by_case[c] for c in sampled)
            if mv0 is not None and mv1 is not None:
                deltas.append(mv1 - mv0)
        if deltas:
            lo_pct = 100 * (1 - ci) / 2
            hi_pct = 100 * (1 + ci) / 2
            ci_low = float(np.percentile(deltas, lo_pct))
            ci_high = float(np.percentile(deltas, hi_pct))

    return DeltaResult(
        v0=point_v0,
        v1=point_v1,
        delta=point_delta,
        ci_low=ci_low,
        ci_high=ci_high,
        n_cases=len(case_ids),
    )


# Stable reporting order; schema_adherence last (it is sourced from test_runs,
# not metric_scores, per the standing decision).
METRIC_ORDER = [
    "detection_rate",
    "hallucination_rate",
    "type_accuracy",
    "date_accuracy",
    "attribution_accuracy",
    "negation_handling",
    "negation_false_positive",
    "negation_false_negative",
    "schema_adherence",
]


@dataclass(frozen=True)
class MetricRecord:
    """One per-(version, provider, metric, case) count, already summed over the
    3 attempts. The loader emits these; the 8 matcher metrics come from
    `metric_scores`, `schema_adherence` from `test_runs`."""

    version: str
    provider: str
    metric: str
    case_id: str
    numerator: int
    denominator: int


@dataclass(frozen=True)
class PointDelta:
    """A v0 -> v1 point comparison with no CI (used for the per-provider and
    per-category breakdowns, where N per group is too small for a meaningful
    bootstrap)."""

    v0: float | None
    v1: float | None
    delta: float | None
    n_cases: int


@dataclass(frozen=True)
class Report:
    metrics: list[str]
    slices: dict[str, dict[str, DeltaResult]]  # slice -> metric -> CI'd delta
    by_provider: dict[str, dict[str, PointDelta]]  # provider -> metric (all-30)
    by_category: dict[str, dict[str, PointDelta]]  # category -> metric (all-30)


def _point_delta(
    v0_by_case: Mapping[str, tuple[int, int]],
    v1_by_case: Mapping[str, tuple[int, int]],
    case_ids: Sequence[str],
) -> PointDelta:
    v0 = micro_average(v0_by_case.get(c, (0, 0)) for c in case_ids)
    v1 = micro_average(v1_by_case.get(c, (0, 0)) for c in case_ids)
    delta = v1 - v0 if v0 is not None and v1 is not None else None
    return PointDelta(v0=v0, v1=v1, delta=delta, n_cases=len(case_ids))


def build_report(
    records: Sequence[MetricRecord],
    *,
    categories: Mapping[str, str],
    held_out_ids: set[str],
    n_resamples: int = 1000,
    seed: int = 0,
) -> Report:
    """Assemble the full v0 -> v1 comparison from per-case counts.

    Three CI'd slices (visible / held_out / all, ADR-004) pooled across
    providers, plus per-provider and per-category point tables on all-30.
    """
    present = {r.metric for r in records}
    metrics = [m for m in METRIC_ORDER if m in present]
    all_case_ids = sorted({r.case_id for r in records})

    # pooled across providers + attempts: (version, metric) -> case_id -> [num, den]
    pooled: dict[tuple[str, str], dict[str, list[int]]] = {}
    # pooled across cases: (version, provider, metric) -> [num, den]
    prov_pool: dict[tuple[str, str, str], list[int]] = {}
    for r in records:
        cell = pooled.setdefault((r.version, r.metric), {}).setdefault(
            r.case_id, [0, 0]
        )
        cell[0] += r.numerator
        cell[1] += r.denominator
        pcell = prov_pool.setdefault((r.version, r.provider, r.metric), [0, 0])
        pcell[0] += r.numerator
        pcell[1] += r.denominator

    def by_case(version: str, metric: str) -> dict[str, tuple[int, int]]:
        return {
            c: (v[0], v[1]) for c, v in pooled.get((version, metric), {}).items()
        }

    slice_ids = {
        "visible": [c for c in all_case_ids if c not in held_out_ids],
        "held_out": [c for c in all_case_ids if c in held_out_ids],
        "all": list(all_case_ids),
    }

    slices: dict[str, dict[str, DeltaResult]] = {}
    for sname, ids in slice_ids.items():
        slices[sname] = {}
        for m in metrics:
            v0c = {c: by_case("v0", m).get(c, (0, 0)) for c in ids}
            v1c = {c: by_case("v1", m).get(c, (0, 0)) for c in ids}
            slices[sname][m] = bootstrap_delta_ci(
                v0c, v1c, ids, n_resamples=n_resamples, seed=seed
            )

    by_provider: dict[str, dict[str, PointDelta]] = {}
    for p in sorted({r.provider for r in records}):
        p_cases = sorted({r.case_id for r in records if r.provider == p})
        by_provider[p] = {}
        for m in metrics:
            v0 = micro_average([tuple(prov_pool.get(("v0", p, m), [0, 0]))])
            v1 = micro_average([tuple(prov_pool.get(("v1", p, m), [0, 0]))])
            delta = v1 - v0 if v0 is not None and v1 is not None else None
            by_provider[p][m] = PointDelta(v0, v1, delta, len(p_cases))

    by_category: dict[str, dict[str, PointDelta]] = {}
    for cat in sorted({categories[c] for c in all_case_ids if c in categories}):
        cat_ids = [c for c in all_case_ids if categories.get(c) == cat]
        by_category[cat] = {}
        for m in metrics:
            by_category[cat][m] = _point_delta(
                by_case("v0", m), by_case("v1", m), cat_ids
            )

    return Report(
        metrics=metrics,
        slices=slices,
        by_provider=by_provider,
        by_category=by_category,
    )


def report_to_payload(
    report: Report,
    *,
    baseline: str,
    candidate: str,
    generated_at: str,
    seed: int,
    n_resamples: int,
) -> dict[str, Any]:
    """Serialize a Report to a JSON-ready dict (the comparison artifact the
    dashboard reads at build time), tagged with run metadata.

    `baseline` / `candidate` record which two agent versions this report
    compares (e.g. "v0" -> "v1"), so the artifact self-identifies the
    comparison regardless of its filename.
    """
    payload = asdict(report)
    payload["baseline"] = baseline
    payload["candidate"] = candidate
    payload["generated_at"] = generated_at
    payload["seed"] = seed
    payload["n_resamples"] = n_resamples
    return payload
