"""Re-score the stored v0 runs through the judged-band matcher.

MUTATES `metric_scores`: for every v0 visible-24 run it re-runs the matcher with
the LLM judge enabled (ceiling 0.80, floor 0.50, Claude Sonnet 4.6 in the band),
re-scores, and UPDATEs the 8 matcher-derived metric rows. `schema_adherence` is
not matcher-derived and is left untouched. The agent outputs are read from
`actual_output`; no extractor calls are made. The only token spend is the judge,
and verdicts are cached at `data/judge_cache.json`, so a re-run is free.

The old 0.80-cutoff numbers are preserved in docs/v0-matcher-validation.md and
docs/v0-failure-analysis.md. Run: `.venv/bin/python scripts/rescore_v0.py`.
"""
from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

load_dotenv("/Users/rani/Desktop/sideProjects/MemoCheck/.env")
import psycopg  # noqa: E402

from memocheck.agent.schema import ExtractedMemo  # noqa: E402
from memocheck.db.persistence import case_score_to_metrics  # noqa: E402
from memocheck.evals.dataset import load_test_cases  # noqa: E402
from memocheck.evals.judge import JudgeCache, make_judge  # noqa: E402
from memocheck.evals.matcher import _load_default_embedder, match  # noqa: E402
from memocheck.evals.scorer import score_case  # noqa: E402

REPO = Path("/Users/rani/Desktop/sideProjects/MemoCheck")
MATCHER_METRICS = {
    "detection_rate", "hallucination_rate", "type_accuracy", "date_accuracy",
    "attribution_accuracy", "negation_handling", "negation_false_positive",
    "negation_false_negative",
}

embed = _load_default_embedder()
api_calls = 0


def counting_complete(**kwargs):
    global api_calls
    api_calls += 1
    import litellm

    return litellm.completion(**kwargs)


def micro(sums: dict[str, list[int]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name, (num, den) in sums.items():
        out[name] = (num / den) if den else None
    return out


def main() -> None:
    cases = {c.id: c for c in load_test_cases(REPO / "data" / "transcripts")}
    cache = JudgeCache(REPO / "data" / "judge_cache.json")

    old_sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    new_sums: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tr.id, tr.test_case_id, tr.actual_output,
                       ms.metric_name, ms.numerator, ms.denominator
                FROM test_runs tr JOIN metric_scores ms ON ms.test_run_id = tr.id
                WHERE tr.agent_version='v0' AND tr.error_message IS NULL
                  AND tr.actual_output IS NOT NULL
                  AND ms.metric_name = ANY(%s)
                """,
                (list(MATCHER_METRICS),),
            )
            for _id, _case, _ao, name, num, den in cur.fetchall():
                old_sums[name][0] += num
                old_sums[name][1] += den

            cur.execute(
                """
                SELECT id, test_case_id, actual_output
                FROM test_runs
                WHERE agent_version='v0' AND error_message IS NULL
                  AND actual_output IS NOT NULL
                ORDER BY test_case_id
                """
            )
            runs = cur.fetchall()

        print(f"re-scoring {len(runs)} v0 runs through the judged band ...")
        with conn.cursor() as cur:
            for run_id, case_id, actual in runs:
                case = cases[case_id]
                agent = ExtractedMemo.model_validate(actual)
                judge = make_judge(
                    case.transcript, cache=cache, complete=counting_complete
                )
                mr = match(case.ground_truth, agent, embedder=embed, judge=judge)
                score = score_case(mr, default_tz=case.memo_recorded_at.tzinfo)
                rows = [
                    m
                    for m in case_score_to_metrics(score, schema_valid=True)
                    if m["name"] in MATCHER_METRICS
                ]
                for m in rows:
                    new_sums[m["name"]][0] += m["numerator"]
                    new_sums[m["name"]][1] += m["denominator"]
                cur.executemany(
                    """
                    UPDATE metric_scores SET numerator=%s, denominator=%s, score=%s
                    WHERE test_run_id=%s AND metric_name=%s
                    """,
                    [
                        (m["numerator"], m["denominator"], m["score"], run_id, m["name"])
                        for m in rows
                    ],
                )
        conn.commit()

    accepted = sum(1 for v in cache.values() if v)
    print(f"\njudge: {len(cache)} unique band pairs cached, {accepted} accepted, "
          f"{len(cache) - accepted} rejected; {api_calls} live API calls this run")
    old, new = micro(old_sums), micro(new_sums)
    print("\nmetric                     old (0.80 cutoff)   new (judged band)")
    for name in sorted(MATCHER_METRICS):
        o = "n/a" if old[name] is None else f"{old[name] * 100:.1f}%"
        n = "n/a" if new[name] is None else f"{new[name] * 100:.1f}%"
        print(f"  {name:24s} {o:>12s}        {n:>12s}"
              f"   ({new_sums[name][0]}/{new_sums[name][1]})")


if __name__ == "__main__":
    main()
