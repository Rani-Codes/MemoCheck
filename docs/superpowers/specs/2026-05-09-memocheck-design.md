# MemoCheck Design Spec
**Date:** 2026-05-09
**Status:** Approved

---

## What We Are Building

MemoCheck is two things built together:

1. A Python agent that takes a voice memo transcript and returns structured intent as JSON (todos, calendar events, reminders, notes, named entities).
2. A rigorous evaluation suite built with DeepEval that measures how well the agent performs across real transcripts and multiple LLM providers, with a focus on known failure modes.

The artifact is the combination. The agent exists to be evaluated. The evaluation exists to surface and quantify real failure modes. The hero output is a published before/after study showing that systematic evaluation and iteration measurably improves agent reliability.

---

## Scope

### Build list

- Python agent: transcript string in, structured JSON out
- Test suite: ~30 real voice memo transcripts with hand-labeled ground truth
- DeepEval evaluation harness with 5 headline metrics
- Multi-provider benchmark across 4 LLM providers via LiteLLM
- Results stored in Postgres (Digital Ocean, Basic plan, ~$15/month)
- Static results dashboard deployed to Vercel free tier
- README documenting methodology, findings, and reproduction steps
- 90-second Loom walkthrough

### Do not build

- Real-time audio recording or transcription pipeline
- Web app with auth, user accounts, or file uploads
- Pip-installable library or PyPI publishing
- Custom eval framework (DeepEval handles this)
- Multi-language support
- More than 4 LLM providers
- More than ~30-40 test cases
- Fine-tuning
- Vector database or RAG
- Any mobile UI, browser extension, or desktop app

If a feature is not on the build list, the answer is no.

---

## Architecture

```
Transcripts (JSON)
        |
        v
Agent (Python, LiteLLM)
        |
        v
DeepEval Eval Harness
        |
        v
Postgres (Digital Ocean)
        |
        v
Static Dashboard (Vercel)
```

The agent and the eval harness are independent. The agent can be replaced or iterated on without touching the eval suite.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Language | Python 3.11+ |
| LLM provider abstraction | LiteLLM |
| Schema validation | Pydantic |
| Eval framework | DeepEval |
| Database | Postgres 16, Digital Ocean Basic plan ($15/month) |
| DB driver | psycopg |
| Migrations | Plain SQL files in db/migrations/ |
| CLI | typer |
| Dashboard | Static HTML + CSS |
| Charts | matplotlib/seaborn, rendered as PNGs at build time |
| Dashboard deploy | Digital Ocean |
| CI | GitHub Actions (lint + type-check + deepeval test run) |
| Audio transcription | Whisper API (one-off, ~$0.30 total) |

**Provider abstraction note:** LiteLLM is the single interface for all providers. Providers are selected by passing a model string: `"anthropic/claude-haiku-4-5"`, `"openai/gpt-4.1-mini"`, `"gemini/gemini-2.5-flash"`, `"groq/llama-3.3-70b-versatile"`. Adding a new provider requires no code changes.

---

## Repository Structure

```
memocheck/
├── README.md
├── pyproject.toml
├── docker-compose.yml          # Postgres for local dev
├── .env.example
├── .github/workflows/
│   └── ci.yml
├── src/
│   └── memocheck/
│       ├── agent/
│       │   ├── schema.py       # Pydantic models
│       │   ├── prompts/
│       │   │   ├── v0.py
│       │   │   └── v1.py
│       │   └── extractor.py    # LiteLLM call + validation + retry
│       ├── evals/
│       │   ├── metrics/
│       │   │   ├── date_accuracy.py
│       │   │   ├── action_completeness.py
│       │   │   ├── hallucination.py
│       │   │   ├── semantic_fidelity.py
│       │   │   └── negation_handling.py
│       │   └── runner.py
│       ├── db/
│       │   ├── models.py
│       │   └── migrations/
│       └── cli.py
├── data/
│   └── transcripts/            # ~30 JSON test cases
├── dashboard/
│   ├── index.html
│   └── charts/
├── scripts/
│   ├── transcribe.py
│   └── build_dashboard.py
└── tests/
    ├── test_agent.py
    ├── test_metrics.py
    └── eval_suite.py
```

---

## Build Order (Sequential)

Work proceeds phase by phase. Each phase is complete before the next begins.

1. **Scaffolding:** pyproject.toml, .gitignore, Docker Compose with Postgres, README skeleton, GitHub Actions CI stub
2. **Schema:** Pydantic models for ExtractedMemo and all sub-types
3. **Agent v0:** extractor.py calling LiteLLM with one provider, one hardcoded transcript returning valid JSON
4. **All providers:** confirm all 4 model strings work end-to-end
5. **Test data:** record ~20 real voice memos, transcribe with Whisper, hand-label ground truth; write ~10 synthetic edge cases (6-8 of these must cover negation, disfluency, and retraction)
6. **DeepEval metrics:** implement all 5 custom metrics
7. **Eval runner:** iterate over test cases x providers x 3 runs, persist to Postgres
8. **v0 full run:** collect baseline results
9. **Analysis:** identify top 1-2 failure modes from v0 results
10. **Agent v1:** improved prompt driven by v0 findings
11. **v1 full run:** collect v1 results, compare to v0
12. **Dashboard:** build_dashboard.py generates charts + flat JSON, index.html displays results
13. **README + Loom:** write final README, record walkthrough, deploy

---

## The Agent

### Input

A transcript string and the memo's recorded timestamp (ISO 8601). The timestamp is injected into the prompt so relative date references resolve correctly.

### Output schema

```python
class ExtractedMemo(BaseModel):
    todos: list[TodoItem]
    events: list[CalendarEvent]
    reminders: list[Reminder]
    notes: list[str]
    entities: list[Entity]

class TodoItem(BaseModel):
    description: str
    due_date: Optional[date]
    assignee: Optional[str]

class CalendarEvent(BaseModel):
    title: str
    start_datetime: datetime
    duration_minutes: Optional[int]
    location: Optional[str]
    attendees: list[str]

class Reminder(BaseModel):
    description: str
    remind_at: Optional[datetime]

class Entity(BaseModel):
    name: str
    kind: Literal["person", "place", "organization"]
```

### Call flow

```
extractor.py
  1. Build messages: system prompt (v0 or v1) with current date injected
  2. Call litellm.completion() with response_format=ExtractedMemo
  3. Parse response into Pydantic model
  4. On ValidationError: retry once with the error appended to context
  5. On second failure: return typed ExtractionError (never silently swallow)
```

Temperature is hardcoded to 0 for reproducibility.

### Prompt strategy

**v0:** Minimal system prompt. Tells the model what the schema is and what the current date is. No examples, no chain-of-thought. Deliberately simple so v0 fails in measurable, reproducible ways.

**v1:** Built after v0 results are analyzed. Likely changes: explicit date resolution instructions with current-date anchoring, negative examples for known failure modes (especially negation and retraction), brief chain-of-thought before final JSON output.

---

## Test Data

### Real memos (~20 cases)

Record voice memos throughout the day. Transcribe with Whisper API (one call per file, ~$0.30 total). Hand-label ground truth for each.

### Synthetic edge cases (~10 cases)

Constructed to cover failure modes that self-recordings may not hit. Allocation:

- 6-8 cases: negation, disfluency, and retraction scenarios ("scratch that", "don't forget NOT to", mid-sentence corrections, double negatives)
- 2-4 cases: remaining edge cases (ambiguous attribution, implicit context, numerical hallucination triggers)

This allocation ensures the Negation Handling metric has N=8-10, making it statistically defensible.

### Test case format

```json
{
  "id": "memo_001",
  "category": "vague_dates",
  "transcript": "Remind me to call the dentist sometime next week...",
  "memo_recorded_at": "2026-05-08T09:30:00Z",
  "ground_truth": {
    "todos": [],
    "reminders": [
      {
        "description": "call dentist",
        "remind_at_constraint": "any_time_in_week_of_2026-05-11"
      }
    ],
    "events": [],
    "notes": [],
    "entities": []
  }
}
```

Ground truth supports exact matches and constraint-based matches for date fields.

---

## Evaluation Suite

### Headline metrics (5)

**1. Action Completeness (Recall)**
What percentage of ground-truth action items appear in the agent output?
Computed via semantic match using GEval on action descriptions. Covers todos, reminders, and events.

**2. Hallucination Rate (Precision)**
What percentage of agent output items have no corresponding ground-truth item?
Inverse of completeness. Computed the same way. A high hallucination rate means the agent is adding phantom tasks.

**3. Date Resolution Accuracy**
For each extracted date, is it correct given the memo's recorded timestamp as anchor?
Scored objectively without an LLM judge. Supports constraint-based ground truth (e.g., "any time in week of X").

**4. Semantic Description Fidelity**
How closely does the extracted description match the ground-truth description in meaning?
Uses GEval. Catches errors that completeness alone misses: "email John" becoming "call John" scores as complete but fails fidelity.

**5. Negation Handling Accuracy**
Did the agent correctly ignore retracted or negated statements?
Scored against negation-specific test cases. V0 is expected to fail here; v1 with explicit negation instructions should show clear improvement.

### Sanity check (reported in methodology, not a headline metric)

**Schema Adherence:** percentage of outputs passing strict Pydantic validation on the first attempt with no retry. Stored in `test_runs.schema_valid`. Reported in the methodology section for transparency.

### Runner logic

```
for each test_case in data/transcripts/:
    for each provider in [anthropic, openai, gemini, groq]:
        for run in range(3):
            output = extractor.run(test_case.transcript, provider)
            scores = score_all_metrics(output, test_case.ground_truth)
            persist(test_run, metric_scores) to Postgres
```

Total: 4 providers x 30 cases x 3 runs = 360 runs per agent version. Two versions = 720 LLM calls. Estimated cost: under $10.

---

## Database

**Digital Ocean Managed Postgres, Basic plan ($15/month).** Provisioned before the first eval run, torn down after results are published.

For local dev: Docker Compose running Postgres 16.

### Schema

```sql
CREATE TABLE test_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    test_case_id TEXT NOT NULL,
    transcript TEXT NOT NULL,
    expected_output JSONB NOT NULL,
    actual_output JSONB,
    schema_valid BOOLEAN NOT NULL,
    latency_ms INT,
    cost_usd NUMERIC(10, 6),
    error_message TEXT
);

CREATE TABLE metric_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_run_id UUID NOT NULL REFERENCES test_runs(id),
    metric_name TEXT NOT NULL,
    score NUMERIC(5, 4) NOT NULL,
    threshold NUMERIC(5, 4),
    passed BOOLEAN NOT NULL,
    explanation TEXT
);

CREATE INDEX ON test_runs (agent_version, provider);
CREATE INDEX ON test_runs (created_at DESC);
CREATE INDEX ON metric_scores (test_run_id);
```

---

## Dashboard

Static HTML page. No backend, no build framework. Results are read from Postgres at build time by `scripts/build_dashboard.py`, which writes flat JSON files and generates matplotlib PNGs. The HTML page consumes those static assets.

### Seven sections

1. Headline finding (one sentence, one number)
2. Provider leaderboard table (4 providers x 5 metrics)
3. Heatmap (provider x failure category, color coded by score)
4. Before/after bar chart (v0 vs v1 on each metric)
5. Methodology (test set construction, metric definitions, schema adherence reported here)
6. Limitations (N=30, English only, single annotator, LLM judge error rate)
7. Reproduction instructions + embedded Loom video

Deployed to Digital Ocean App Platform. Results are static; no request-time DB calls.

---

## Cost Budget

| Item | List Price | Out of Pocket |
|---|---|---|
| Whisper API (~20 memos) | $0.30 | $0.30 |
| Claude Haiku eval runs | $3-4 | $3-4 |
| GPT-4.1 mini eval runs | $2-3 | $2-3 |
| GPT-4.1 mini as LLM judge | $0.50-1.50 | $0.50-1.50 |
| Gemini 2.5 Flash (free tier) | $0 | $0 |
| Llama 3.3 70B via Groq (free tier) | $0 | $0 |
| Postgres on Digital Ocean (~1 month) | $15 | $0 (DO credits) |
| Dashboard hosting on DO App Platform | $5 | $0 (DO credits) |
| **Total** | **~$26-29** | **~$6-9** |

Real out-of-pocket cost is roughly $6-9, covering only the Whisper, Claude, and OpenAI calls. DO infrastructure is covered by existing credits.

Set hard spending limits on OpenAI ($10) and Anthropic ($10) before any code runs to prevent runaway retry loops.

**LLM judge:** DeepEval is configured to use GPT-4.1 mini as the judge model for all GEval metrics (Action Completeness, Hallucination Rate, Semantic Description Fidelity). Date Resolution Accuracy and Negation Handling Accuracy are scored deterministically with no judge call.

---

## Validation Requirements

Two validations are required before results are publishable:

1. **Manual judge spot-check:** For 20 randomly sampled metric scores, manually verify the LLM-as-judge is producing reasonable judgments. If unreliable, tighten the rubric and re-run.
2. **Schema validation:** Every agent output must pass strict Pydantic validation. Track and report the failure rate. Do not silently coerce.

Both are documented in the methodology section of the dashboard.

---

## Definition of Done

- [ ] All ~30 test cases run end-to-end against all 4 providers without errors
- [ ] v0 and v1 results both stored in Postgres
- [ ] v1 shows measurable improvement on at least one metric
- [ ] Static dashboard publicly accessible at a deployed URL
- [ ] README contains: tagline, what/why, quickstart, architecture, methodology, results table, limitations, future work, reproduction instructions
- [ ] 90-second Loom walkthrough recorded and linked from README
- [ ] Repo public on GitHub with clean commit history
- [ ] CI runs on every push
