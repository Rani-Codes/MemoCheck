"""Matcher spot-check + hallucination-counting validation (CLAUDE.md validation #1).

Read-only. Re-runs the embedding+Hungarian matcher on the stored v0 outputs for
the visible-24 slice and:

  1. Reconciles recomputed detection/hallucination totals against the numbers
     stored in Postgres (validates end-to-end counting, no token spend).
  2. Emits 20 randomly sampled matched (GT item, agent item) pairings for manual
     verification.
  3. Emits every hallucination (unmatched agent item), sorted by its best cosine
     to any GT item in the same case, so near-miss false hallucinations surface.

No LLM calls: embeddings are local sentence-transformers per ADR-002.
Run with the project venv: `.venv/bin/python scripts/matcher_spotcheck.py`.
"""
from __future__ import annotations

import os
import random

import numpy as np
from dotenv import load_dotenv

load_dotenv("/Users/rani/Desktop/sideProjects/MemoCheck/.env")
import psycopg  # noqa: E402

from memocheck.agent.schema import ExtractedMemo  # noqa: E402
from memocheck.evals.matcher import (  # noqa: E402
    _load_default_embedder,
    flatten,
    match,
)
from memocheck.evals.schema import GroundTruthExtractedMemo  # noqa: E402

VISIBLE = [
    "memo_002", "memo_003", "memo_004", "memo_006", "memo_007", "memo_008",
    "memo_010", "memo_012", "memo_013", "memo_014", "memo_015", "memo_017",
    "memo_018", "memo_019", "memo_020", "memo_021", "synth_001", "synth_002",
    "synth_003", "synth_004", "synth_005", "synth_006", "synth_007", "synth_008",
]
SAMPLE_N = 20
SEED = 0
DETAIL_COS = 0.55  # show unmatched items in full at/above this best-cosine

embed = _load_default_embedder()
_cache: dict[str, np.ndarray] = {}


def vec(text: str) -> np.ndarray:
    if text not in _cache:
        v = embed([text])[0]
        _cache[text] = v / (np.linalg.norm(v) or 1.0)
    return _cache[text]


def cos(a: str, b: str) -> float:
    return float(vec(a) @ vec(b))


def parse_gt(obj: dict) -> GroundTruthExtractedMemo:
    if "ground_truth" in obj:
        obj = obj["ground_truth"]
    return GroundTruthExtractedMemo.model_validate(obj)


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT test_case_id, provider, transcript, expected_output, actual_output
            FROM test_runs
            WHERE agent_version='v0' AND error_message IS NULL
              AND test_case_id = ANY(%s)
            ORDER BY test_case_id, provider
            """,
            (VISIBLE,),
        )
        runs = cur.fetchall()

        cur.execute(
            """
            SELECT ms.metric_name, SUM(ms.numerator), SUM(ms.denominator)
            FROM test_runs tr JOIN metric_scores ms ON ms.test_run_id=tr.id
            WHERE tr.agent_version='v0' AND tr.error_message IS NULL
              AND tr.test_case_id = ANY(%s)
              AND ms.metric_name IN ('detection_rate','hallucination_rate')
            GROUP BY ms.metric_name
            """,
            (VISIBLE,),
        )
        db = {m: (int(n), int(d)) for m, n, d in cur.fetchall()}

    matched_pairs: list[dict] = []
    hallucinations: list[dict] = []
    det_miss: list[dict] = []
    tot_match = tot_unmatched_gt = tot_unmatched_agent = 0
    n_runs = 0

    for case, prov, transcript, expected, actual in runs:
        if actual is None:
            continue
        n_runs += 1
        gt = parse_gt(expected)
        agent = ExtractedMemo.model_validate(actual)
        mr = match(gt, agent, embedder=embed)

        tot_match += len(mr.matched)
        tot_unmatched_gt += len(mr.unmatched_gt)
        tot_unmatched_agent += len(mr.unmatched_agent)

        for g, a in mr.matched:
            matched_pairs.append(
                {"case": case, "prov": prov, "gt_t": g.type, "gt": g.text,
                 "ag_t": a.type, "ag": a.text, "cos": cos(g.text, a.text),
                 "tx": transcript}
            )
        gt_texts = [g.text for g in flatten(gt)]
        ag_texts = [a.text for a in flatten(agent)]
        for a in mr.unmatched_agent:
            best = max(((cos(a.text, gt), gt) for gt in gt_texts),
                       default=(0.0, None))
            hallucinations.append(
                {"case": case, "prov": prov, "ag_t": a.type, "ag": a.text,
                 "best_cos": best[0], "best_gt": best[1], "tx": transcript}
            )
        for g in mr.unmatched_gt:
            best = max(((cos(g.text, at), at) for at in ag_texts),
                       default=(0.0, None))
            det_miss.append(
                {"case": case, "prov": prov, "gt_t": g.type, "gt": g.text,
                 "best_cos": best[0], "best_ag": best[1], "tx": transcript}
            )

    det_relevant = tot_match + tot_unmatched_gt
    hal_relevant = tot_match + tot_unmatched_agent

    print("=" * 78)
    print(f"RUNS scored: {n_runs}  (expected 288)")
    print("=" * 78)
    print("\n## COUNT RECONCILIATION (recomputed from raw outputs vs Postgres)")
    print(f"  detection      recomputed {tot_match}/{det_relevant}   "
          f"db {db['detection_rate'][0]}/{db['detection_rate'][1]}   "
          f"{'MATCH' if (tot_match, det_relevant)==db['detection_rate'] else 'MISMATCH'}")
    print(f"  hallucination  recomputed {tot_unmatched_agent}/{hal_relevant}   "
          f"db {db['hallucination_rate'][0]}/{db['hallucination_rate'][1]}   "
          f"{'MATCH' if (tot_unmatched_agent, hal_relevant)==db['hallucination_rate'] else 'MISMATCH'}")

    rng = random.Random(SEED)
    sample = rng.sample(matched_pairs, min(SAMPLE_N, len(matched_pairs)))
    print(f"\n## 20 SAMPLED MATCHED PAIRS (seed={SEED}, of {len(matched_pairs)} total)")
    for i, p in enumerate(sample, 1):
        flag = "  <-- LOW" if p["cos"] < 0.82 else ""
        print(f"{i:2d}. [{p['case']}/{p['prov'][:4]}] cos={p['cos']:.3f}{flag}")
        print(f"    GT  ({p['gt_t']}): {p['gt']!r}")
        print(f"    AG  ({p['ag_t']}): {p['ag']!r}")

    print(f"\n## HALLUCINATIONS: {len(hallucinations)} total "
          f"(unmatched agent items). Sorted by best cosine to any GT item.")
    hallucinations.sort(key=lambda h: -h["best_cos"])
    buckets = {">=0.80": 0, "0.70-0.80": 0, "0.55-0.70": 0, "<0.55": 0}
    for h in hallucinations:
        c = h["best_cos"]
        if c >= 0.80:
            buckets[">=0.80"] += 1
        elif c >= 0.70:
            buckets["0.70-0.80"] += 1
        elif c >= 0.55:
            buckets["0.55-0.70"] += 1
        else:
            buckets["<0.55"] += 1
    print(f"  best-cosine buckets: {buckets}")
    print(f"  (any >=0.80 here would indicate a possible threshold/assignment miss)\n")
    shown = [h for h in hallucinations if h["best_cos"] >= DETAIL_COS]
    print(f"  --- detail for best_cos >= {DETAIL_COS} ({len(shown)} items) ---")
    for i, h in enumerate(shown, 1):
        print(f"{i:2d}. [{h['case']}/{h['prov'][:4]}] best_cos={h['best_cos']:.3f}")
        print(f"    AG hallucinated ({h['ag_t']}): {h['ag']!r}")
        print(f"    nearest GT:                    {h['best_gt']!r}")
        print(f"    transcript: {h['tx'][:160]!r}")

    print(f"\n## DETECTION MISSES: {len(det_miss)} total (unmatched GT items). "
          f"detail for best_cos >= {DETAIL_COS} (near-miss = matcher too strict)")
    det_miss.sort(key=lambda h: -h["best_cos"])
    shown_d = [h for h in det_miss if h["best_cos"] >= DETAIL_COS]
    for i, h in enumerate(shown_d, 1):
        print(f"{i:2d}. [{h['case']}/{h['prov'][:4]}] best_cos={h['best_cos']:.3f}")
        print(f"    GT missed ({h['gt_t']}): {h['gt']!r}")
        print(f"    nearest AG:             {h['best_ag']!r}")


if __name__ == "__main__":
    main()
