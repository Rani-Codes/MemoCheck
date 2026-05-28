"""
MemoCheck CLI.

Entry points:
    memocheck run     # execute one eval batch (agent_version x slice x providers)
    memocheck report  # placeholder; populated in step 9 once v0/v1 runs exist
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import get_args

import typer

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
        )


@app.command()
def report() -> None:
    """Aggregate metrics from the DB. Wired up in step 9 once v0 / v1 runs exist."""
    typer.echo("report: not yet implemented (step 9)")


if __name__ == "__main__":
    app()
