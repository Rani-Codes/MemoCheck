"""Band-calibration probe: where do Hungarian-assigned pairs land on cosine?

Read-only. For the v0 visible-24 runs, replicates the matcher's Hungarian
assignment and buckets EVERY assigned (gt, agent) pair by cosine, then lists the
distinct sub-0.80 assigned pairs so the judge band [floor, ceiling) can be set
from evidence: we want the floor below any plausible genuine pair (so nothing
real is auto-rejected unseen) but high enough to skip obvious forced-assignment
junk. No LLM calls.

Run: `.venv/bin/python scripts/matcher_band_probe.py`.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
from scipy.optimize import linear_sum_assignment

load_dotenv("/Users/rani/Desktop/sideProjects/MemoCheck/.env")
import psycopg  # noqa: E402

from memocheck.agent.schema import ExtractedMemo  # noqa: E402
from memocheck.evals.matcher import (  # noqa: E402
    _cosine_similarity,
    _load_default_embedder,
    flatten,
)
from memocheck.evals.schema import GroundTruthExtractedMemo  # noqa: E402

VISIBLE = [
    "memo_002", "memo_003", "memo_004", "memo_006", "memo_007", "memo_008",
    "memo_010", "memo_012", "memo_013", "memo_014", "memo_015", "memo_017",
    "memo_018", "memo_019", "memo_020", "memo_021", "synth_001", "synth_002",
    "synth_003", "synth_004", "synth_005", "synth_006", "synth_007", "synth_008",
]
EDGES = [0.0, 0.45, 0.50, 0.60, 0.70, 0.80, 1.01]
embed = _load_default_embedder()


def parse_gt(obj: dict) -> GroundTruthExtractedMemo:
    if "ground_truth" in obj:
        obj = obj["ground_truth"]
    return GroundTruthExtractedMemo.model_validate(obj)


def main() -> None:
    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT expected_output, actual_output
            FROM test_runs
            WHERE agent_version='v0' AND error_message IS NULL
              AND test_case_id = ANY(%s) AND actual_output IS NOT NULL
            """,
            (VISIBLE,),
        )
        rows = cur.fetchall()

    buckets = [0] * (len(EDGES) - 1)
    sub80: dict[tuple[str, str], float] = {}  # distinct assigned pairs below 0.80
    total_assigned = 0
    for expected, actual in rows:
        gt = flatten(parse_gt(expected))
        ag = flatten(ExtractedMemo.model_validate(actual))
        if not gt or not ag:
            continue
        sim = _cosine_similarity(
            embed([i.text for i in gt]), embed([i.text for i in ag])
        )
        r_ind, c_ind = linear_sum_assignment(-sim)
        for r, c in zip(r_ind, c_ind):
            cval = float(sim[r, c])
            total_assigned += 1
            for b in range(len(EDGES) - 1):
                if EDGES[b] <= cval < EDGES[b + 1]:
                    buckets[b] += 1
                    break
            if cval < 0.80:
                key = (gt[r].text, ag[c].text)
                sub80[key] = cval

    print(f"Total Hungarian-assigned pairs across 288 runs: {total_assigned}\n")
    print("Cosine distribution of ASSIGNED pairs (these are the pairs the band gates):")
    for b in range(len(EDGES) - 1):
        lo, hi = EDGES[b], min(EDGES[b + 1], 1.0)
        print(f"  [{lo:.2f}, {hi:.2f}): {buckets[b]:4d}")

    print(f"\nDistinct assigned pairs below 0.80 (deduped): {len(sub80)}")
    print("Judge would be asked about pairs whose cosine >= floor. Listing all,"
          " highest first, so the genuine/junk boundary is visible:\n")
    for (gt_t, ag_t), c in sorted(sub80.items(), key=lambda x: -x[1]):
        print(f"  cos={c:.3f}   GT {gt_t!r}  ~  AG {ag_t!r}")


if __name__ == "__main__":
    main()
