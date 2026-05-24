# MemoCheck
An eval-driven study of how reliably LLM agents extract structured intent from real-world voice memo transcripts.

## Requirements

- **Apple Silicon Mac (M1/M2...)** -- transcription uses `mlx-whisper` for local, free, offline inference via the MLX framework. The first run downloads the selected model to your HuggingFace cache (~150MB for `base`); subsequent runs skip the download. If you're on Intel, swap in the [OpenAI Whisper API](https://platform.openai.com/docs/guides/speech-to-text) and update `scripts/transcribe.py` accordingly.
- Python 3.11+
- Docker Desktop (for local Postgres)

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # add your API keys
docker compose up -d  # start Postgres
```

## Design Decisions
- **Purpose of notes:** The whole reason the field exists is that without it, models invent fake action items for non-actionable content because the schema forces every observation to land somewhere typed.
    - Avoids hallucinations and creating action items that don't exist.
    - Avoids the content getting dropped and having data loss.
    - Con: Agent might put real tasks in the notes field, but this is fine because our evals catch it.
        - If an agent puts a real todo into notes instead of todo, the matcher has no agent-side todo to pair with the ground-truth todo, so Detection Rate drops.

## Architectural and methodology decisions
- These are recorded as ADRs (Architecture Decision Record) in [`docs/adr/`](./docs/adr/).

## Thinking process: eval design

Initially I had planned to use an LLM-as-a-judge to evaluate the agent outputs. That made sense at first, but as I rewrote my evals to take a flattened action-item-metric three-tier approach so an agent's output gets flagged incorrect once instead of twice (see [ADR-001](./docs/adr/001-flattened-action-item-metrics.md)), I had to build a matching algorithm. Since todos, reminders, and calendar events were now being scored from a single pool, the matcher was what picked them apart again.

I went with an embedding similarity + Hungarian algorithm combo (see [ADR-002](./docs/adr/002-embedding-based-matching.md)): encode each item as a vector, build a pairwise cosine similarity matrix, then run the Hungarian algorithm to find the optimal one-to-one pairing above a 0.8 cosine-similarity threshold. The known con is that embeddings can miss nuance (e.g. "buy milk" vs "don't buy milk"), but to avoid premature optimization I leaned on the `negated: true` flag already on the schema. If the spot-check at the end shows the matcher is wrong on more than 5% of cases, I can add an LLM-judge hybrid where embeddings narrow to top-K candidates and the LLM only judges among those.

This new matching design also surfaced something I'd missed. I had been planning to use gpt-4.1-mini as the judge, but it was also one of the agents producing outputs. That's self-preference bias, which is when a model rates its own output higher than others. To avoid it I pushed hard to make scoring deterministic, and after rethinking the evals I was able to build deterministic versions that produced the same results I originally wanted. The LLM-judge ended up only being necessary as a fallback if the matcher itself underperforms.

**TL;DR:** digging into a double-penalty issue on one metric surfaced a deeper one with LLM-as-judge bias, which led me to question whether I needed an LLM judge at all. The answer was no. The result is a cleaner, more robust eval suite where the LLM-judge is only a backup for the matching algorithm. 

Bigger picture: The whole point of evals is to drive decisions for better agent creation. The numbers aren't the point, the iterations they unlock are.

**On the small-N concern:** I deliberately chose depth over breadth. ~30 hand-labeled cases targeting specific known failure modes (vague dates, negation, disfluencies) gives a sharper diagnostic signal than hundreds of shallow cases. Stripe's recent agentic benchmark used 11 hard tasks for the same reason, which is good external precedent for the deterministic-graders-plus-hard-tasks approach I adopted ([Stripe Engineering blog](https://stripe.com/blog/can-ai-agents-build-real-stripe-integrations)).

## Failure modes

Aggregate metrics tell you whether v1 improved on v0, but they don't tell you why. This section names 3-5 specific failure patterns observed in v0, each with the real transcript, the real agent output (captured via `raw_response`), and a one-sentence diagnosis. These examples are what drive v1 prompt iteration directly, and they make the writeup concrete instead of just statistical.

> *Examples will be populated after the v0 evaluation run completes. Each entry follows this format:*

### [Failure mode name]
- **Transcript:** ...
- **Agent output:** ...
- **Diagnosis:** ...

## Engineering Notes
- **`pip install -e .` (editable install):** links the package to your local `src/` so code changes reflect immediately without reinstalling. Use this during development. Use `pip install .` (no `-e`) when you want a static install, like in a Docker image or CI.
- If you're using a virtual environment, make sure VS Code's Python interpreter is pointing to that venv (Cmd+Shift+P > "Python: Select Interpreter").
