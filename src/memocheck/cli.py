"""
MemoCheck CLI.

Entry points:
    memocheck run     # execute one eval batch (agent_version x slice x providers)
    memocheck report  # placeholder; populated in step 9 once v0/v1 runs exist
"""
from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import get_args

import typer
from dotenv import load_dotenv

from memocheck.evals.dataset import (
    Slice,
    filter_slice,
    load_held_out_ids,
    load_test_cases,
)
from memocheck.evals.runner import ProviderConfig, run_batch

app = typer.Typer(no_args_is_help=True, add_completion=False)

DEFAULT_PROVIDERS: dict[str, ProviderConfig] = {
    "anthropic": ProviderConfig(
        provider="anthropic", model="anthropic/claude-haiku-4-5"
    ),
    "openai": ProviderConfig(provider="openai", model="openai/gpt-4.1-mini"),
    "gemini": ProviderConfig(
        provider="gemini", model="gemini/gemini-3.1-flash-lite-preview"
    ),
    "groq": ProviderConfig(provider="groq", model="groq/llama-3.3-70b-versatile"),
}

ALLOWED_SLICES = set(get_args(Slice))


def _load_prompt(agent_version: str) -> str:
    module = importlib.import_module(f"memocheck.agent.prompts.{agent_version}")
    prompt = getattr(module, "SYSTEM_PROMPT", None)
    if not isinstance(prompt, str):
        raise typer.BadParameter(
            f"prompt module memocheck.agent.prompts.{agent_version} "
            "must export a SYSTEM_PROMPT string"
        )
    return prompt


@app.command()
def run(
    agent_version: str = typer.Option("v0", help="prompt module name: v0 / v1 / v2"),
    case_slice: str = typer.Option(
        "visible", "--slice", help="visible | held_out | all (ADR-004)"
    ),
    attempts: int = typer.Option(
        3, help="target successful attempts per (provider, case)"
    ),
    providers: str = typer.Option(
        "anthropic,openai,gemini,groq", help="comma-separated provider keys"
    ),
    transcripts: Path = typer.Option(Path("data/transcripts")),
    held_out_ids: Path = typer.Option(Path("data/held_out_ids.txt")),
) -> None:
    """Run the eval batch. Resumable: existing successful attempts in DB are skipped."""
    # Load .env so DATABASE_URL and provider API keys (read by litellm) are present.
    load_dotenv()
    if case_slice not in ALLOWED_SLICES:
        raise typer.BadParameter(
            f"--slice must be one of {sorted(ALLOWED_SLICES)}, got {case_slice!r}"
        )

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        typer.echo("DATABASE_URL not set", err=True)
        raise typer.Exit(1)

    provider_keys = [p.strip() for p in providers.split(",") if p.strip()]
    unknown = [p for p in provider_keys if p not in DEFAULT_PROVIDERS]
    if unknown:
        raise typer.BadParameter(
            f"unknown provider key(s): {unknown}. "
            f"Known: {sorted(DEFAULT_PROVIDERS)}"
        )
    selected = [DEFAULT_PROVIDERS[p] for p in provider_keys]

    system_prompt = _load_prompt(agent_version)
    cases = load_test_cases(transcripts)
    held = load_held_out_ids(held_out_ids)
    cases = filter_slice(cases, held, case_slice)  # type: ignore[arg-type]

    if not cases:
        typer.echo(f"no cases match slice={case_slice!r}; nothing to do", err=True)
        raise typer.Exit(0)

    import psycopg

    from memocheck.db.persistence import apply_schema
    from memocheck.evals.judge import JudgeCache, make_judge
    from memocheck.evals.matcher import Judge

    # One persisted judge cache across the batch: band verdicts are reused across
    # providers/attempts and survive resumed runs, so the judge is called at most
    # once per distinct (model, gt_label, agent_label) pair (ADR-002).
    judge_cache = JudgeCache(Path("data/judge_cache.json"))

    def judge_factory(transcript: str) -> Judge:
        return make_judge(transcript, cache=judge_cache)

    typer.echo(
        f"agent_version={agent_version} slice={case_slice} "
        f"providers={[p.provider for p in selected]} "
        f"cases={len(cases)} attempts={attempts}"
    )

    with psycopg.connect(db_url) as conn:
        apply_schema(conn)
        run_batch(
            agent_version=agent_version,
            providers=selected,
            cases=cases,
            system_prompt=system_prompt,
            target_attempts=attempts,
            conn=conn,
            judge_factory=judge_factory,
        )


def _fmt(x: float | None) -> str:
    return "  n/a" if x is None else f"{x:.3f}"


def _fmt_delta(x: float | None) -> str:
    return "  n/a" if x is None else f"{x:+.3f}"


def _fmt_ci(lo: float | None, hi: float | None) -> str:
    if lo is None or hi is None:
        return ""
    return f"[{lo:+.3f}, {hi:+.3f}]"


def _print_report(rep) -> None:  # type: ignore[no-untyped-def]
    typer.echo("v0 -> v1 deltas, pooled across providers (95% bootstrap CI)")
    typer.echo(
        f"{'metric':<24}{'slice':<10}{'v0':>7}{'v1':>7}{'delta':>8}  95% CI"
    )
    for m in rep.metrics:
        for s in ("visible", "held_out", "all"):
            d = rep.slices[s][m]
            typer.echo(
                f"{m:<24}{s:<10}{_fmt(d.v0):>7}{_fmt(d.v1):>7}"
                f"{_fmt_delta(d.delta):>8}  {_fmt_ci(d.ci_low, d.ci_high)}"
            )

    typer.echo("\nper-provider, all-30 (point deltas, no CI)")
    typer.echo(f"{'provider':<12}{'metric':<24}{'v0':>7}{'v1':>7}{'delta':>8}")
    for provider, metrics in rep.by_provider.items():
        for m, pd in metrics.items():
            typer.echo(
                f"{provider:<12}{m:<24}{_fmt(pd.v0):>7}{_fmt(pd.v1):>7}"
                f"{_fmt_delta(pd.delta):>8}"
            )

    typer.echo("\nper-category, all-30 (point deltas, no CI)")
    typer.echo(f"{'category':<26}{'metric':<24}{'v0':>7}{'v1':>7}{'delta':>8}")
    for category, metrics in rep.by_category.items():
        for m, pd in metrics.items():
            typer.echo(
                f"{category:<26}{m:<24}{_fmt(pd.v0):>7}{_fmt(pd.v1):>7}"
                f"{_fmt_delta(pd.delta):>8}"
            )


@app.command()
def report(
    held_out_ids: Path = typer.Option(Path("data/held_out_ids.txt")),
    composition: Path = typer.Option(
        Path("docs/test-set-composition.md"),
        help="source of case_id -> category for the per-category breakdown",
    ),
    out: Path = typer.Option(Path("data/results/v0_vs_v1.json")),
    seed: int = typer.Option(0, help="bootstrap RNG seed (reproducible CIs)"),
    n_resamples: int = typer.Option(1000, help="bootstrap resamples per ADR-005"),
) -> None:
    """Aggregate v0 -> v1 deltas + bootstrap CIs from the DB (step 9).

    Deterministic and token-free. Schema Adherence is sourced from
    `test_runs.schema_valid` (network/infra failures excluded), not the biased
    `metric_scores` copy. Writes a JSON artifact for the dashboard and prints a
    readable summary.
    """
    from datetime import datetime, timezone

    import psycopg

    from memocheck.db.persistence import load_metric_records
    from memocheck.evals.report import (
        build_report,
        parse_categories,
        report_to_payload,
    )

    load_dotenv()
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        typer.echo("DATABASE_URL not set", err=True)
        raise typer.Exit(1)

    held = load_held_out_ids(held_out_ids)
    categories = parse_categories(composition.read_text())

    with psycopg.connect(db_url) as conn:
        records = load_metric_records(conn)

    if not records:
        typer.echo("no eval runs found; run `memocheck run` first", err=True)
        raise typer.Exit(1)

    rep = build_report(
        records,
        categories=categories,
        held_out_ids=held,
        n_resamples=n_resamples,
        seed=seed,
    )
    payload = report_to_payload(
        rep,
        # fixed to the v0 -> v1 comparison for now; becomes --baseline/--candidate
        # flags if a v2 is added (the loader/DB are already version-agnostic).
        baseline="v0",
        candidate="v1",
        generated_at=datetime.now(timezone.utc).isoformat(),
        seed=seed,
        n_resamples=n_resamples,
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    _print_report(rep)
    typer.echo(f"\nwrote {out}")


if __name__ == "__main__":
    app()
