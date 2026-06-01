"""
Persistence layer for eval runs.

Writes one `test_runs` row + 9 `metric_scores` rows per (provider, case,
attempt). Raw counts go into `numerator` / `denominator` so the dashboard
can micro-average across cases; the `score` column is denormalized
convenience (NULL when denominator = 0).
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.types.json import Jsonb

from memocheck.agent.schema import ExtractionError
from memocheck.evals.report import MetricRecord, responded
from memocheck.evals.runner import CaseResult
from memocheck.evals.scorer import CaseScore

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def apply_schema(conn: psycopg.Connection) -> None:
    """Apply all migration .sql files in order. Idempotent (CREATE IF NOT EXISTS)."""
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        with conn.cursor() as cur:
            cur.execute(path.read_text())
        conn.commit()


def count_successful_attempts(
    conn: psycopg.Connection, *, agent_version: str
) -> dict[tuple[str, str], int]:
    """Returns {(provider, test_case_id): num_successful_attempts} for resumability.

    A 'successful' attempt is a test_run row whose error_message IS NULL.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT provider, test_case_id, COUNT(*) AS n
            FROM test_runs
            WHERE agent_version = %s AND error_message IS NULL
            GROUP BY provider, test_case_id
            """,
            (agent_version,),
        )
        return {(provider, case_id): n for provider, case_id, n in cur.fetchall()}


def load_metric_records(
    conn: psycopg.Connection, *, versions: tuple[str, ...] = ("v0", "v1")
) -> list[MetricRecord]:
    """Load per-(version, provider, metric, case) counts for the report.

    The 8 matcher metrics come from `metric_scores` (summed across the 3
    attempts). `schema_adherence` is derived from `test_runs` instead: its
    numerator is the count of first-attempt-valid runs and its denominator is
    the count of runs where the model actually responded (network/infra
    failures excluded via `responded`), per the standing decision. The
    `metric_scores` copy of schema_adherence is ignored because it is biased
    (only written for successful extractions).
    """
    records: list[MetricRecord] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.agent_version, t.provider, m.metric_name, t.test_case_id,
                   SUM(m.numerator), SUM(m.denominator)
            FROM metric_scores m
            JOIN test_runs t ON t.id = m.test_run_id
            WHERE m.metric_name <> 'schema_adherence'
              AND t.agent_version = ANY(%s)
            GROUP BY t.agent_version, t.provider, m.metric_name, t.test_case_id
            """,
            (list(versions),),
        )
        for version, provider, metric, case_id, num, den in cur.fetchall():
            records.append(
                MetricRecord(version, provider, metric, case_id, int(num), int(den))
            )

        # schema_adherence from test_runs: valid / responded per (version,
        # provider, case). Aggregated in Python so the responded() rule (the
        # standing decision) lives in exactly one place.
        cur.execute(
            """
            SELECT agent_version, provider, test_case_id, schema_valid, error_message
            FROM test_runs
            WHERE agent_version = ANY(%s)
            """,
            (list(versions),),
        )
        valid: dict[tuple[str, str, str], int] = {}
        responded_n: dict[tuple[str, str, str], int] = {}
        for version, provider, case_id, schema_valid, error_message in cur.fetchall():
            if not responded(error_message):
                continue
            key = (version, provider, case_id)
            responded_n[key] = responded_n.get(key, 0) + 1
            if schema_valid:
                valid[key] = valid.get(key, 0) + 1

    for key, den in responded_n.items():
        version, provider, case_id = key
        records.append(
            MetricRecord(
                version, provider, "schema_adherence", case_id, valid.get(key, 0), den
            )
        )
    return records


def case_score_to_metrics(
    score: CaseScore, *, schema_valid: bool
) -> list[dict[str, Any]]:
    """Flatten a CaseScore into per-metric rows for metric_scores."""
    return [
        _metric("detection_rate", score.detection_matched, score.detection_relevant),
        _metric(
            "hallucination_rate",
            score.hallucination_unmatched,
            score.hallucination_relevant,
        ),
        _metric("type_accuracy", score.type_correct, score.type_pair_count),
        _metric("date_accuracy", score.date_correct, score.date_pair_count),
        _metric(
            "attribution_accuracy",
            score.attribution_correct,
            score.attribution_pair_count,
        ),
        _metric(
            "negation_handling", score.negation_correct, score.negation_pair_count
        ),
        _metric(
            "negation_false_positive",
            score.negation_false_positive,
            score.negation_pair_count,
        ),
        _metric(
            "negation_false_negative",
            score.negation_false_negative,
            score.negation_pair_count,
        ),
        _metric("schema_adherence", 1 if schema_valid else 0, 1),
    ]


def _metric(name: str, numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "name": name,
        "numerator": numerator,
        "denominator": denominator,
        "score": (numerator / denominator) if denominator > 0 else None,
    }


def insert_case_result(
    conn: psycopg.Connection,
    *,
    agent_version: str,
    provider: str,
    model: str,
    attempt: int,
    case_result: CaseResult,
    expected_output: dict[str, Any],
    transcript: str,
) -> uuid.UUID:
    """Insert one test_run row + its metric_scores rows. Returns the test_run UUID."""
    extraction = case_result.extraction
    is_error = isinstance(extraction.output, ExtractionError)
    actual_output: Optional[dict[str, Any]]
    error_message: Optional[str]
    if is_error:
        actual_output = None
        error_message = extraction.output.error  # type: ignore[union-attr]
    else:
        actual_output = extraction.output.model_dump(mode="json")
        error_message = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO test_runs (
                agent_version, provider, model, test_case_id, attempt,
                transcript, expected_output, actual_output, raw_llm_response,
                schema_valid, latency_ms, cost_usd, error_message
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                agent_version,
                provider,
                model,
                case_result.test_case_id,
                attempt,
                transcript,
                Jsonb(expected_output),
                Jsonb(actual_output) if actual_output is not None else None,
                extraction.raw_response,
                extraction.schema_valid,
                extraction.latency_ms,
                extraction.cost_usd,
                error_message,
            ),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT ... RETURNING id produced no row")
        test_run_id: uuid.UUID = row[0]

        if case_result.score is not None:
            metric_rows = case_score_to_metrics(
                case_result.score, schema_valid=extraction.schema_valid
            )
            cur.executemany(
                """
                INSERT INTO metric_scores
                    (test_run_id, metric_name, numerator, denominator, score)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        test_run_id,
                        m["name"],
                        m["numerator"],
                        m["denominator"],
                        m["score"],
                    )
                    for m in metric_rows
                ],
            )

    conn.commit()
    return test_run_id
