# Frozen DB snapshot

A point-in-time export of the two Postgres tables that back **every number in the writeup**:
`test_runs` (the raw agent runs) and `metric_scores` (the per-run deterministic scores). This
is the gold-standard reproducibility artifact for the benchmark.

Generated 2026-06-02 from the project Postgres. Read-only export, no schema changes.

## Why this exists

The committed report JSONs (`data/results/*.json`) carry only **aggregate rates** plus
per-provider / per-category point deltas and `n_cases` (a case count). They do **not** carry
the per-case numerator/denominator counts. Without those, an outside reader cannot:

- recompute the 95% bootstrap CIs (the bootstrap resamples per-case scores, which were not
  published),
- reproduce the Floor-1 per-attempt tables or the "15 of 346 cells" run-to-run variance stat
  (see `docs/v2-failure-analysis.md`),
- check the per-case counts cited in the failure analyses (e.g. memo_009 3/12 -> 12/12), or
- re-derive the matched pairs behind the 20/20 matcher spot-check
  (`docs/v0-matcher-validation.md`).

There is a second, stronger reason this dump is **required and not optional**: the project's
own Floor-1 finding is that the agent is non-deterministic at temperature 0 (15 of 346
(version, provider, case) cells return different scores across reruns). That means "just
re-run it to check my numbers" does **not** reproduce the published figures. A fresh run
yields different per-case counts and therefore different CIs. Freezing the data is the only
way to make the fine-grained claims independently auditable.

Because scoring is deterministic (ADR-002) and the judge cache is committed
(`data/judge_cache.json`), freezing the agent outputs here makes the **entire downstream
pipeline bit-for-bit reproducible**: a reader re-runs the committed scorer over
`test_runs.actual_output` and reproduces the exact matched pairs, type/date/negation scores,
CIs, and spot-check, despite Floor-1 nondeterminism.

## Files

### `test_runs.csv` (1146 rows)

One row per (agent_version, provider, test_case_id, attempt) run, including failed retries.
Columns mirror `src/memocheck/db/migrations/001_init.sql`:

`id, created_at, agent_version, provider, model, test_case_id, attempt, transcript,
expected_output, actual_output, raw_llm_response, schema_valid, latency_ms, cost_usd,
error_message`

`actual_output`, `expected_output`, and `raw_llm_response` are JSON/text and contain embedded
newlines, so the file is ~15.7k physical lines but **1146 logical CSV rows** (RFC-4180
quoting; parse with a real CSV reader, not line counting). Per version: v0 418, v1 362,
v2 366 rows, of which exactly **360 succeeded** each (4 providers x 30 cases x 3 attempts);
the remainder are errored retries (`error_message IS NOT NULL`), kept as part of the record
per the resumability design in CLAUDE.md.

### `metric_scores.csv` (9720 rows)

`metric_scores` joined to `test_runs` so every score row is self-describing (no UUID lookup
needed). 1080 successful runs x 9 metrics = 9720 rows. Columns:

`test_run_id, agent_version, provider, model, test_case_id, attempt, metric_name, numerator,
denominator, score, threshold, passed, explanation`

`numerator` / `denominator` are the raw counts; micro-average with
`SUM(numerator) / SUM(denominator)`, never `AVG(score)`. `score` is the denormalized
`numerator/denominator` (NULL when `denominator = 0`, i.e. the metric is undefined for that
case).

## How to reproduce the published numbers

1. **Recompute aggregates / CIs / floors from counts alone:** load `metric_scores.csv`, group
   by the slice you want (all / visible / held_out, by provider, by category), micro-average,
   and bootstrap-resample the per-case scores (1000 resamples, seed 0) per ADR-005.
2. **Re-run the full scorer from frozen outputs:** feed `test_runs.actual_output` back through
   the committed scorer (`src/memocheck/evals/`) with the committed `data/judge_cache.json`.
   Deterministic by ADR-002, so it reproduces matching, scores, and CIs exactly.

## Refresh

Re-exported by the same two `\copy` statements used to create it (ordered by
agent_version, provider, test_case_id, attempt for a stable, diff-friendly file). Regenerate
after any new eval run so the snapshot tracks the DB.
