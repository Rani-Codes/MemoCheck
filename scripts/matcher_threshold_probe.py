"""Threshold-calibration probe for the matcher (diagnostic for validation #1).

Read-only. Quantifies how many v0 visible-24 hallucinations are mutual-orphan
false negatives (the agent item and its nearest GT item are BOTH unmatched and
are each other's nearest neighbor -> they should have paired), sweeps the
detection/hallucination totals across candidate thresholds, and lists the
distinct new matches a lower threshold would create so they can be eyeballed
for wrong matches.

No LLM calls. Run: `.venv/bin/python scripts/matcher_threshold_probe.py`.
"""
from __future__ import annotations

import os

import numpy as np
from dotenv import load_dotenv

load_dotenv("/Users/rani/Desktop/sideProjects/MemoCheck/.env")
import psycopg  # noqa: E402

from memocheck.agent.schema import ExtractedMemo  # noqa: E402
from memocheck.evals.matcher import _load_default_embedder, flatten, match  # noqa: E402
from memocheck.evals.schema import GroundTruthExtractedMemo  # noqa: E402

VISIBLE = [
    "memo_002", "memo_003", "memo_004", "memo_006", "memo_007", "memo_008",
    "memo_010", "memo_012", "memo_013", "memo_014", "memo_015", "memo_017",
    "memo_018", "memo_019", "memo_020", "memo_021", "synth_001", "synth_002",
    "synth_003", "synth_004", "synth_005", "synth_006", "synth_007", "synth_008",
]
THRESHOLDS = [0.80, 0.78, 0.75, 0.72, 0.70, 0.65]

embed = _load_default_embedder()
_cache: dict[str, np.ndarray] = {}


def vec(t: str) -> np.ndarray:
    if t not in _cache:
        v = embed([t])[0]
        _cache[t] = v / (np.linalg.norm(v) or 1.0)
    return _cache[t]


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
            SELECT test_case_id, expected_output, actual_output
            FROM test_runs
            WHERE agent_version='v0' AND error_message IS NULL
              AND test_case_id = ANY(%s) AND actual_output IS NOT NULL
            ORDER BY test_case_id, provider
            """,
            (VISIBLE,),
        )
        runs = [(c, parse_gt(e), ExtractedMemo.model_validate(a)) for c, e, a in cur.fetchall()]

    # --- A. mutual-orphan analysis at the live 0.8 threshold ---
    mutual_orphans: list[tuple[str, str, str, float]] = []  # case, ag, gt, cos
    genuine_extras = 0
    for case, gt, agent in runs:
        mr = match(gt, agent, embedder=embed)
        un_gt_texts = {g.text for g in mr.unmatched_gt}
        gt_texts = [g.text for g in flatten(gt)]
        for a in mr.unmatched_agent:
            if not gt_texts:
                genuine_extras += 1
                continue
            best_c, best_g = max((cos(a.text, g), g) for g in gt_texts)
            if best_g in un_gt_texts:
                mutual_orphans.append((case, a.text, best_g, best_c))
            else:
                genuine_extras += 1

    print("## A. HALLUCINATION DECOMPOSITION (live threshold 0.80)")
    print(f"  total hallucinations:        63")
    print(f"  genuine extras (nearest GT already matched): {genuine_extras}")
    print(f"  mutual-orphan false negatives (should have paired): {len(mutual_orphans)}")
    mo_cos = sorted((c for *_, c in mutual_orphans), reverse=True)
    if mo_cos:
        print(f"  mutual-orphan cosine range: {mo_cos[0]:.3f} .. {mo_cos[-1]:.3f}")
    print(f"  => false-hallucination share: {len(mutual_orphans)}/63 = "
          f"{len(mutual_orphans)/63*100:.0f}%  (threshold check is 5%)")

    print("\n  distinct mutual-orphan pairs (deduped across runs):")
    seen = set()
    for case, ag, gt, c in sorted(mutual_orphans, key=lambda x: -x[3]):
        k = (case, ag, gt)
        if k in seen:
            continue
        seen.add(k)
        print(f"    cos={c:.3f} [{case}]  AG {ag!r}  ~  GT {gt!r}")

    # --- B. threshold sweep ---
    print("\n## B. THRESHOLD SWEEP (detection & hallucination micro-totals)")
    print(f"  {'thresh':>7} {'detection':>16} {'hallucination':>16}")
    for th in THRESHOLDS:
        m = ug = ua = 0
        for _, gt, agent in runs:
            mr = match(gt, agent, embedder=embed, threshold=th)
            m += len(mr.matched); ug += len(mr.unmatched_gt); ua += len(mr.unmatched_agent)
        det = m / (m + ug) if (m + ug) else 0
        hal = ua / (m + ua) if (m + ua) else 0
        print(f"  {th:>7.2f} {f'{det*100:.1f}% {m}/{m+ug}':>16} {f'{hal*100:.1f}% {ua}/{m+ua}':>16}")

    # --- C. distinct NEW matches created going 0.80 -> 0.70 (eyeball for wrong matches) ---
    print("\n## C. NEW MATCHES INTRODUCED at threshold 0.70 vs 0.80 (deduped)")
    new_pairs = set()
    for _, gt, agent in runs:
        hi = {(g.text, a.text) for g, a in match(gt, agent, embedder=embed, threshold=0.80).matched}
        lo = match(gt, agent, embedder=embed, threshold=0.70).matched
        for g, a in lo:
            if (g.text, a.text) not in hi:
                new_pairs.add((round(cos(g.text, a.text), 3), g.type, g.text, a.type, a.text))
    for c, gt_t, gt_x, ag_t, ag_x in sorted(new_pairs, reverse=True):
        print(f"  cos={c:.3f}  GT({gt_t}) {gt_x!r}  <->  AG({ag_t}) {ag_x!r}")


if __name__ == "__main__":
    main()
