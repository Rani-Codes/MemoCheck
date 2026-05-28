import uuid
from datetime import datetime, timezone

from memocheck.agent.schema import (
    ExtractedMemo,
    ExtractionError,
    ExtractionResult,
    TodoItem,
)
from memocheck.evals.runner import CaseResult, ProviderConfig, run_batch, run_case
from memocheck.evals.schema import (
    GroundTruthExtractedMemo,
    GroundTruthTodoItem,
    TestCase,
)


def _test_case(transcript="hi", todos=None, id="memo_test"):
    return TestCase(
        id=id,
        transcript=transcript,
        memo_recorded_at=datetime(2026, 5, 4, 9, 30, tzinfo=timezone.utc),
        ground_truth=GroundTruthExtractedMemo(todos=todos or []),
    )


def _ok_extraction(memo: ExtractedMemo, schema_valid: bool = True) -> ExtractionResult:
    return ExtractionResult(
        output=memo,
        schema_valid=schema_valid,
        latency_ms=123,
        cost_usd=0.0001,
        raw_response="{}",
    )


def _err_extraction(msg: str = "broken JSON") -> ExtractionResult:
    return ExtractionResult(
        output=ExtractionError(error=msg),
        schema_valid=False,
        latency_ms=42,
        cost_usd=0.00005,
        raw_response="not json",
    )


def _ok_extractor(memo: ExtractedMemo, schema_valid: bool = True):
    def _e(**_kw):
        return _ok_extraction(memo, schema_valid=schema_valid)

    return _e


def _err_extractor(msg: str):
    def _e(**_kw):
        return _err_extraction(msg)

    return _e


def _capturing_insert(captured: list[dict]):
    def _i(_conn, **kwargs):
        captured.append(kwargs)
        return uuid.uuid4()

    return _i


def _const_count(existing: dict):
    def _c(_conn, *, agent_version):
        return existing

    return _c


def test_run_case_happy_path_returns_score():
    case = _test_case(todos=[GroundTruthTodoItem(description="call dentist")])
    agent_output = ExtractedMemo(todos=[TodoItem(description="call the dentist")])

    result = run_case(
        case,
        model="claude-haiku-4-5",
        system_prompt="x",
        extractor=_ok_extractor(agent_output),
    )

    assert isinstance(result, CaseResult)
    assert result.test_case_id == "memo_test"
    assert result.score is not None
    assert result.score.detection_matched == 1
    assert result.score.detection_relevant == 1
    assert result.extraction.schema_valid is True


def test_run_case_extraction_error_returns_none_score():
    case = _test_case(todos=[GroundTruthTodoItem(description="something")])

    result = run_case(
        case,
        model="any",
        system_prompt="x",
        extractor=_err_extractor("model refused"),
    )

    assert result.test_case_id == "memo_test"
    assert result.score is None
    assert isinstance(result.extraction.output, ExtractionError)
    assert result.extraction.output.error == "model refused"


def test_run_case_passes_correct_args_to_extractor():
    """Extractor must receive transcript, ISO memo_recorded_at, model, and prompt."""
    case = _test_case(transcript="buy milk")
    seen: dict = {}

    def spy_extractor(**kwargs):
        seen.update(kwargs)
        return _ok_extraction(ExtractedMemo())

    run_case(
        case,
        model="gpt-4.1-mini",
        system_prompt="SYS",
        extractor=spy_extractor,
    )

    assert seen["transcript"] == "buy milk"
    assert seen["model"] == "gpt-4.1-mini"
    assert seen["system_prompt"] == "SYS"
    # memo_recorded_at must be ISO string (extractor does .replace on it)
    assert "2026-05-04" in seen["memo_recorded_at"]


def test_run_case_schema_invalid_but_output_valid_still_scores():
    """When extractor used retry (schema_valid=False) but still produced a valid
    ExtractedMemo, the scorer should still run on that output."""
    case = _test_case(todos=[GroundTruthTodoItem(description="call dentist")])
    agent_output = ExtractedMemo(todos=[TodoItem(description="call the dentist")])

    result = run_case(
        case,
        model="x",
        system_prompt="x",
        extractor=_ok_extractor(agent_output, schema_valid=False),
    )

    assert result.score is not None
    assert result.score.detection_matched == 1
    assert result.extraction.schema_valid is False


def test_run_batch_iterates_provider_case_attempt_grid_when_db_is_empty():
    """No prior runs -> every (provider × case × attempt) slot executes."""
    cases = [_test_case(id="memo_001"), _test_case(id="memo_002")]
    providers = [
        ProviderConfig(provider="anthropic", model="anthropic/claude"),
        ProviderConfig(provider="openai", model="openai/gpt"),
    ]
    inserts: list[dict] = []

    run_batch(
        agent_version="v0",
        providers=providers,
        cases=cases,
        system_prompt="x",
        target_attempts=3,
        conn=object(),
        extractor=_ok_extractor(ExtractedMemo()),
        count_fn=_const_count({}),
        insert_fn=_capturing_insert(inserts),
        progress=None,
    )

    assert len(inserts) == 2 * 2 * 3  # 12 slots
    # Each attempt for first (provider, case) should be 1, 2, 3
    first_three_attempts = [i["attempt"] for i in inserts[:3]]
    assert first_three_attempts == [1, 2, 3]
    # Provider grouping (6 slots each = 2 cases × 3 attempts)
    providers_seen = [i["provider"] for i in inserts]
    assert providers_seen[:6] == ["anthropic"] * 6
    assert providers_seen[6:] == ["openai"] * 6


def test_run_batch_resumability_skips_already_completed_slots():
    """When existing successful attempts cover some pairs, only top up to target."""
    cases = [_test_case(id="memo_001"), _test_case(id="memo_002")]
    providers = [ProviderConfig(provider="anthropic", model="x")]
    inserts: list[dict] = []

    # memo_001 already has 2 successful attempts; memo_002 has 0
    existing = {("anthropic", "memo_001"): 2}

    run_batch(
        agent_version="v0",
        providers=providers,
        cases=cases,
        system_prompt="x",
        target_attempts=3,
        conn=object(),
        extractor=_ok_extractor(ExtractedMemo()),
        count_fn=_const_count(existing),
        insert_fn=_capturing_insert(inserts),
        progress=None,
    )

    # memo_001 needs 1 more (attempt 3); memo_002 needs all 3 (attempts 1,2,3)
    assert len(inserts) == 4
    by_case = {(i["case_result"].test_case_id, i["attempt"]) for i in inserts}
    assert by_case == {
        ("memo_001", 3),
        ("memo_002", 1),
        ("memo_002", 2),
        ("memo_002", 3),
    }


def test_run_batch_persists_failed_extractions_too():
    """Failed attempts must still write a row (with error_message)."""
    cases = [_test_case(id="memo_001")]
    providers = [ProviderConfig(provider="anthropic", model="x")]
    inserts: list[dict] = []

    run_batch(
        agent_version="v0",
        providers=providers,
        cases=cases,
        system_prompt="x",
        target_attempts=2,
        conn=object(),
        extractor=_err_extractor("rate limit"),
        count_fn=_const_count({}),
        insert_fn=_capturing_insert(inserts),
        progress=None,
    )

    assert len(inserts) == 2
    for ins in inserts:
        assert ins["case_result"].score is None
        assert isinstance(ins["case_result"].extraction.output, ExtractionError)
