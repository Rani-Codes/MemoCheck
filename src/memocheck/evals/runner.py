"""
Per-case eval execution.

`run_case` composes the agent extractor, matcher, and scorer for a single
TestCase. `run_batch` orchestrates (provider x case x attempt) execution with
resumability: it queries the DB for successful attempts per (provider, case)
and only runs the missing slots up to `target_attempts`. The extractor and
persistence functions are injectable so the runner is unit-testable without
making real LLM calls or hitting Postgres.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

from memocheck.agent.extractor import extract
from memocheck.agent.schema import ExtractionError, ExtractionResult
from memocheck.evals.matcher import Judge, match
from memocheck.evals.schema import TestCase
from memocheck.evals.scorer import CaseScore, score_case

ExtractorFn = Callable[..., ExtractionResult]


@dataclass(frozen=True)
class ProviderConfig:
    """One row in the run grid.

    `provider` is a short DB label (e.g. "anthropic"); `model` is the litellm
    routing string (e.g. "anthropic/claude-haiku-4-5").
    """

    provider: str
    model: str


@dataclass
class CaseResult:
    test_case_id: str
    extraction: ExtractionResult
    score: Optional[CaseScore]  # None when extraction errored out


def run_case(
    test_case: TestCase,
    *,
    model: str,
    system_prompt: str,
    extractor: ExtractorFn = extract,
    judge: Optional[Judge] = None,
) -> CaseResult:
    extraction = extractor(
        transcript=test_case.transcript,
        memo_recorded_at=test_case.memo_recorded_at.isoformat(),
        model=model,
        system_prompt=system_prompt,
    )
    if isinstance(extraction.output, ExtractionError):
        return CaseResult(
            test_case_id=test_case.id,
            extraction=extraction,
            score=None,
        )
    # Judged band (ADR-002): the judge adjudicates ambiguous-cosine pairs.
    match_result = match(test_case.ground_truth, extraction.output, judge=judge)
    # Localize naive agent datetimes to the memo's offset before scoring (ADR-003).
    return CaseResult(
        test_case_id=test_case.id,
        extraction=extraction,
        score=score_case(match_result, default_tz=test_case.memo_recorded_at.tzinfo),
    )


CountFn = Callable[..., dict[tuple[str, str], int]]
InsertFn = Callable[..., uuid.UUID]
ProgressFn = Callable[[str], None]


def run_batch(
    *,
    agent_version: str,
    providers: list[ProviderConfig],
    cases: list[TestCase],
    system_prompt: str,
    target_attempts: int,
    conn: Any,
    extractor: ExtractorFn = extract,
    count_fn: Optional[CountFn] = None,
    insert_fn: Optional[InsertFn] = None,
    progress: Optional[ProgressFn] = print,
    judge_factory: Optional[Callable[[str], Judge]] = None,
) -> None:
    """Iterate (provider x case x attempt), executing only missing slots.

    Resumability: an attempt 'slot' is filled iff there's a test_runs row with
    `error_message IS NULL` for that (provider, case). On rerun, only the
    unfilled slots (up to `target_attempts`) execute.
    """
    # Imports defer to call time so unit tests can swap count_fn / insert_fn
    # without forcing psycopg to load.
    from memocheck.db.persistence import count_successful_attempts, insert_case_result

    _count = count_fn or count_successful_attempts
    _insert = insert_fn or insert_case_result

    existing = _count(conn, agent_version=agent_version)
    total = sum(
        max(0, target_attempts - existing.get((p.provider, c.id), 0))
        for p in providers
        for c in cases
    )
    done = 0
    for prov in providers:
        for case in cases:
            already = existing.get((prov.provider, case.id), 0)
            for i in range(target_attempts - already):
                attempt_num = already + i + 1
                done += 1
                case_judge = (
                    judge_factory(case.transcript) if judge_factory else None
                )
                result = run_case(
                    case,
                    model=prov.model,
                    system_prompt=system_prompt,
                    extractor=extractor,
                    judge=case_judge,
                )
                _insert(
                    conn,
                    agent_version=agent_version,
                    provider=prov.provider,
                    model=prov.model,
                    attempt=attempt_num,
                    case_result=result,
                    expected_output=case.ground_truth.model_dump(mode="json"),
                    transcript=case.transcript,
                )
                if progress is not None:
                    tag = "ERR" if result.score is None else "OK"
                    progress(
                        f"[{done}/{total}] {prov.provider} {case.id} "
                        f"attempt {attempt_num} {tag}"
                    )
