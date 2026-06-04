"""
baseline -> candidate comparison report (CLI `memocheck report`, step 9).

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
    """One baseline -> candidate comparison: point scores, the delta, and its
    bootstrap CI.

    Any field is None when the metric is undefined for this set of cases (the
    pooled denominator is 0, e.g. a slice with no items of this metric's kind).
    """

    baseline: float | None
    candidate: float | None
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    n_cases: int


def bootstrap_delta_ci(
    baseline_by_case: Mapping[str, tuple[int, int]],
    candidate_by_case: Mapping[str, tuple[int, int]],
    case_ids: Sequence[str],
    *,
    n_resamples: int = 1000,
    seed: int = 0,
    ci: float = 0.95,
) -> DeltaResult:
    """Paired bootstrap CI for the candidate - baseline micro-average delta (ADR-005).

    `baseline_by_case` / `candidate_by_case` map case_id -> (numerator,
    denominator) already pooled across providers and attempts. The comparison is
    paired: the same resampled case_ids index both versions every iteration,
    preserving the case-level pairing. A resample whose pooled denominator is 0
    on either side is skipped (its delta is undefined). The CI is the [2.5, 97.5]
    percentiles of the resampled deltas. Deterministic for a fixed `seed`.
    """
    point_baseline = micro_average(baseline_by_case[c] for c in case_ids)
    point_candidate = micro_average(candidate_by_case[c] for c in case_ids)
    point_delta = (
        point_candidate - point_baseline
        if point_baseline is not None and point_candidate is not None
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
            mb = micro_average(baseline_by_case[c] for c in sampled)
            mc = micro_average(candidate_by_case[c] for c in sampled)
            if mb is not None and mc is not None:
                deltas.append(mc - mb)
        if deltas:
            lo_pct = 100 * (1 - ci) / 2
            hi_pct = 100 * (1 + ci) / 2
            ci_low = float(np.percentile(deltas, lo_pct))
            ci_high = float(np.percentile(deltas, hi_pct))

    return DeltaResult(
        baseline=point_baseline,
        candidate=point_candidate,
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
    """A baseline -> candidate point comparison with no CI (used for the
    per-provider and per-category breakdowns, where N per group is too small for
    a meaningful bootstrap)."""

    baseline: float | None
    candidate: float | None
    delta: float | None
    n_cases: int


@dataclass(frozen=True)
class Report:
    metrics: list[str]
    slices: dict[str, dict[str, DeltaResult]]  # slice -> metric -> CI'd delta
    by_provider: dict[str, dict[str, PointDelta]]  # provider -> metric (all-30)
    by_category: dict[str, dict[str, PointDelta]]  # category -> metric (all-30)


def _point_delta(
    baseline_by_case: Mapping[str, tuple[int, int]],
    candidate_by_case: Mapping[str, tuple[int, int]],
    case_ids: Sequence[str],
) -> PointDelta:
    base = micro_average(baseline_by_case.get(c, (0, 0)) for c in case_ids)
    cand = micro_average(candidate_by_case.get(c, (0, 0)) for c in case_ids)
    delta = cand - base if base is not None and cand is not None else None
    return PointDelta(baseline=base, candidate=cand, delta=delta, n_cases=len(case_ids))


def build_report(
    records: Sequence[MetricRecord],
    *,
    baseline: str,
    candidate: str,
    categories: Mapping[str, str],
    held_out_ids: set[str],
    n_resamples: int = 1000,
    seed: int = 0,
) -> Report:
    """Assemble the full baseline -> candidate comparison from per-case counts.

    `baseline` / `candidate` are the two agent versions to compare (e.g. "v0"
    and "v1", or "v1" and "v2"); the records must contain rows for both. Three
    CI'd slices (visible / held_out / all, ADR-004) pooled across providers,
    plus per-provider and per-category point tables on all-30.
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
            basec = {c: by_case(baseline, m).get(c, (0, 0)) for c in ids}
            candc = {c: by_case(candidate, m).get(c, (0, 0)) for c in ids}
            slices[sname][m] = bootstrap_delta_ci(
                basec, candc, ids, n_resamples=n_resamples, seed=seed
            )

    by_provider: dict[str, dict[str, PointDelta]] = {}
    for p in sorted({r.provider for r in records}):
        p_cases = sorted({r.case_id for r in records if r.provider == p})
        by_provider[p] = {}
        for m in metrics:
            base_pair = prov_pool.get((baseline, p, m), [0, 0])
            cand_pair = prov_pool.get((candidate, p, m), [0, 0])
            base = micro_average([(base_pair[0], base_pair[1])])
            cand = micro_average([(cand_pair[0], cand_pair[1])])
            delta = cand - base if base is not None and cand is not None else None
            by_provider[p][m] = PointDelta(base, cand, delta, len(p_cases))

    by_category: dict[str, dict[str, PointDelta]] = {}
    for cat in sorted({categories[c] for c in all_case_ids if c in categories}):
        cat_ids = [c for c in all_case_ids if categories.get(c) == cat]
        by_category[cat] = {}
        for m in metrics:
            by_category[cat][m] = _point_delta(
                by_case(baseline, m), by_case(candidate, m), cat_ids
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
