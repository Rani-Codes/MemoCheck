import os
from datetime import datetime, timezone

import pytest

from memocheck.agent.schema import ExtractedMemo, ExtractionResult, TodoItem
from memocheck.db.persistence import (
    apply_schema,
    case_score_to_metrics,
    insert_case_result,
)
from memocheck.evals.runner import CaseResult
from memocheck.evals.schema import (
    GroundTruthExtractedMemo,
    GroundTruthTodoItem,
    TestCase,
)
from memocheck.evals.scorer import CaseScore


def test_case_score_to_metrics_emits_all_nine_metrics():
    score = CaseScore(
        detection_matched=2, detection_relevant=3,
        hallucination_unmatched=1, hallucination_relevant=3,
        type_correct=2, type_pair_count=2,
        date_correct=1, date_pair_count=2,
        attribution_correct=1, attribution_pair_count=1,
        negation_correct=2, negation_pair_count=2,
        negation_false_positive=0, negation_false_negative=0,
    )

    rows = case_score_to_metrics(score, schema_valid=True)

    names = {r["name"] for r in rows}
    assert names == {
        "detection_rate",
        "hallucination_rate",
        "type_accuracy",
        "date_accuracy",
        "attribution_accuracy",
        "negation_handling",
        "negation_false_positive",
        "negation_false_negative",
        "schema_adherence",
    }


def test_case_score_to_metrics_carries_raw_counts():
    score = CaseScore(
        detection_matched=2, detection_relevant=3,
        hallucination_unmatched=1, hallucination_relevant=3,
        type_correct=2, type_pair_count=2,
        date_correct=1, date_pair_count=2,
        attribution_correct=1, attribution_pair_count=1,
        negation_correct=1, negation_pair_count=2,
        negation_false_positive=1, negation_false_negative=0,
    )

    rows = {r["name"]: r for r in case_score_to_metrics(score, schema_valid=True)}

    def nd(name: str) -> tuple[int, int]:
        return rows[name]["numerator"], rows[name]["denominator"]

    assert nd("detection_rate") == (2, 3)
    assert nd("hallucination_rate") == (1, 3)
    assert nd("type_accuracy") == (2, 2)
    assert nd("date_accuracy") == (1, 2)
    assert nd("attribution_accuracy") == (1, 1)
    assert nd("negation_handling") == (1, 2)
    assert nd("negation_false_positive") == (1, 2)
    assert nd("negation_false_negative") == (0, 2)


def test_case_score_to_metrics_schema_adherence_true():
    score = CaseScore()
    rows = {r["name"]: r for r in case_score_to_metrics(score, schema_valid=True)}
    assert rows["schema_adherence"]["numerator"] == 1
    assert rows["schema_adherence"]["denominator"] == 1


def test_case_score_to_metrics_schema_adherence_false():
    score = CaseScore()
    rows = {r["name"]: r for r in case_score_to_metrics(score, schema_valid=False)}
    assert rows["schema_adherence"]["numerator"] == 0
    assert rows["schema_adherence"]["denominator"] == 1


@pytest.fixture
def pg_conn():
    """Postgres connection. Skips the test if DATABASE_URL is unset / unreachable."""
    import psycopg

    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        conn = psycopg.connect(url, connect_timeout=2)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres unreachable: {exc}")
    try:
        # Use a savepoint-style strategy: drop tables before+after to keep test
        # isolated. Cheap on a tiny schema.
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS metric_scores, test_runs CASCADE")
        conn.commit()
        apply_schema(conn)
        yield conn
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS metric_scores, test_runs CASCADE")
        conn.commit()
        conn.close()


@pytest.mark.integration
def test_insert_case_result_writes_test_run_and_nine_metric_rows(pg_conn):
    from memocheck.evals.matcher import match
    from memocheck.evals.scorer import score_case

    gt = GroundTruthExtractedMemo(
        todos=[GroundTruthTodoItem(description="call dentist")]
    )
    test_case = TestCase(
        id="memo_test",
        transcript="Remind me to call dentist.",
        memo_recorded_at=datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc),
        ground_truth=gt,
    )
    agent_output = ExtractedMemo(todos=[TodoItem(description="call dentist")])
    extraction = ExtractionResult(
        output=agent_output,
        schema_valid=True,
        latency_ms=200,
        cost_usd=0.0001,
        raw_response='{"todos":[...]}',
    )
    match_result = match(gt, agent_output)
    case_result = CaseResult(
        test_case_id=test_case.id,
        extraction=extraction,
        score=score_case(match_result),
    )

    run_id = insert_case_result(
        pg_conn,
        agent_version="v0",
        provider="anthropic",
        model="claude-haiku-4-5",
        attempt=1,
        case_result=case_result,
        expected_output=gt.model_dump(mode="json"),
        transcript=test_case.transcript,
    )

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM test_runs WHERE id = %s", (run_id,))
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT COUNT(*) FROM metric_scores WHERE test_run_id = %s", (run_id,)
        )
        assert cur.fetchone()[0] == 9


@pytest.mark.integration
def test_insert_case_result_handles_extraction_error(pg_conn):
    from memocheck.agent.schema import ExtractionError

    test_case = TestCase(
        id="memo_test_err",
        transcript="x",
        memo_recorded_at=datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc),
        ground_truth=GroundTruthExtractedMemo(),
    )
    extraction = ExtractionResult(
        output=ExtractionError(error="model refused"),
        schema_valid=False,
        latency_ms=10,
        cost_usd=0.0,
        raw_response="...",
    )
    case_result = CaseResult(
        test_case_id=test_case.id, extraction=extraction, score=None
    )

    run_id = insert_case_result(
        pg_conn,
        agent_version="v0",
        provider="anthropic",
        model="claude-haiku-4-5",
        attempt=1,
        case_result=case_result,
        expected_output=test_case.ground_truth.model_dump(mode="json"),
        transcript=test_case.transcript,
    )

    with pg_conn.cursor() as cur:
        cur.execute(
            "SELECT error_message, actual_output FROM test_runs WHERE id = %s",
            (run_id,),
        )
        err, actual = cur.fetchone()
        assert err == "model refused"
        assert actual is None
        cur.execute(
            "SELECT COUNT(*) FROM metric_scores WHERE test_run_id = %s", (run_id,)
        )
        # No score -> no metric rows
        assert cur.fetchone()[0] == 0
