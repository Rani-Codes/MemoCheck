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
- **Why there's a `notes` field:** The output schema includes a `notes` field for non-actionable observations ("the coffee on 5th was great"). Without it, the LLM has nowhere to put genuinely irrelevant content and tends to invent todos or reminders that don't belong there. Notes act as a pressure valve that keeps the actionable fields clean.

## What I Learned
- **`pip install -e .` (editable install):** links the package to your local `src/` so code changes reflect immediately without reinstalling. Use this during development. Use `pip install .` (no `-e`) when you want a static install, like in a Docker image or CI.

## Engineering Trip-Ups
- If you're using a virtual environment, make sure VS Code's Python interpreter is pointing to that venv (Cmd+Shift+P > "Python: Select Interpreter").