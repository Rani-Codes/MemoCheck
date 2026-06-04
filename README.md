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

## Results

**Headline:** eval-driven iteration took the agent from v0 to v1 by cutting the hallucination rate by about 60% (0.057 -> 0.023) and pushing type-classification accuracy to near-perfect (0.958 -> 0.997). Both wins are real, not noise: their 95% bootstrap confidence intervals (1000 resamples, see [ADR-005](./docs/adr/005-bootstrap-confidence-intervals.md)) exclude zero. The same single prompt change also cost a small drop in detection (0.982 -> 0.966), which I report instead of hiding.

Every number below is micro-averaged across 4 providers x 30 cases x 3 attempts. Micro-averaged means each metric is the sum of its raw per-case numerators divided by the sum of its denominators (for example, total correctly-typed items over total matched pairs), not the average of per-case percentages. That stops a case with one action item from counting as much as a case with five, which a naive per-case average would do. **v1 is the agent of record.** The full frozen run data lives in [`data/db_snapshot/`](./data/db_snapshot/) so the table is auditable even though the agents are not bit-for-bit reproducible (the [v2 failure analysis](./docs/v2-failure-analysis.md) explains the run-to-run nondeterminism).

### v0 -> v1, all 30 cases

| Metric | v0 | v1 | Delta | 95% CI | Read |
|---|---|---|---|---|---|
| Type accuracy | 0.958 | 0.997 | +0.039 | [+0.004, +0.089] | **win** (CI excludes 0) |
| Hallucination rate | 0.057 | 0.023 | -0.034 | [-0.071, -0.004] | **win** (lower is better) |
| Detection rate | 0.982 | 0.966 | -0.016 | [-0.033, +0.002] | disclosed cost (see below) |
| Date accuracy | 0.772 | 0.795 | +0.024 | [-0.056, +0.112] | flat (CI straddles 0) |
| Attribution accuracy | 0.975 | 0.981 | +0.006 | [-0.011, +0.019] | flat |
| Negation handling | 0.995 | 1.000 | +0.005 | [0.000, +0.018] | solved at v0 |
| Schema adherence | 1.000 | 1.000 | 0.000 | [0, 0] | validation result |

Higher is better for everything except hallucination rate, where lower is better.

### The three-act story

**Act 1, the eval finds three real gaps.** v0's aggregate scores looked decent, but scoring each case separately surfaced three specific weaknesses: date resolution sat at ~0.77, the agent confused item types (Todo vs Reminder vs CalendarEvent), and it invented items that were not there (worst on OpenAI at a 0.105 hallucination rate).

**Act 2, v1 fixes type and hallucination, at the cost of the detection rate.** v1's prompt changes pushed type accuracy to 0.997 and dropped the hallucination rate to 0.023, both with CIs that exclude zero. The catch: the same change made the agent emit fewer items overall, 33 fewer across the run, which breaks down as 23 fewer false positives (the hallucination win) plus 10 fewer true positives (the detection cost). One knob moved both numbers. Detection slipped 0.016 (its CI [-0.033, +0.002] straddles zero, but the item-dropping is real, not a scoring artifact). Full breakdown in the [v1 detection retrospective](./docs/v1-detection-retrospective.md).

**Act 3, v2 attacks date and the number does not move.** v2's one job was to lift date accuracy. All-30 date went 0.795 -> 0.766 with a CI of [-0.086, +0.026]: no move. That is the honest result, and the [v2 failure analysis](./docs/v2-failure-analysis.md) explains why. At 30 cases the effect any single prompt edit can produce (~0.03) is smaller than the test set's case-sampling noise (~±0.06), so date is sample-size-bound. This is a finding about the benchmark's resolution, not a v2 failure, and it is why there is no v3.

### Two metrics that were already solved

- **Negation handling** is near-perfect from v0 (0.995, then 1.000 at v1 and v2 with a zero-width CI). Current models handle "scratch that" retractions and false-positive traps well, so this is reported as a single finding ("negation handled near-perfectly from v0"), not as an iteration story.
- **Schema adherence** is 100% on the first LLM attempt across every provider and version. I read it as a validation result: the structured-output plus Pydantic-validate-and-retry design works. It carries no before/after signal.

### Per-provider, v1 (the agent of record)

| Provider | Type acc | Hallucination | Detection | Date acc |
|---|---|---|---|---|
| Anthropic (Haiku 4.5) | 1.000 | 0.000 | 0.962 | 0.687 |
| Gemini (3.1 Flash Lite Preview) | 1.000 | 0.000 | 1.000 | 0.904 |
| Groq (Llama 3.3 70B) | 1.000 | 0.038 | 0.962 | 0.847 |
| OpenAI (GPT-4.1 mini) | 0.986 | 0.052 | 0.942 | 0.738 |

OpenAI is the hallucination laggard (0.052, still the highest after halving from 0.105 at v0) and took the biggest detection hit. Gemini leads on date accuracy (0.904), but note its latency tail: the median is fine, p95 is ~20s and max ~32s, so pair that accuracy with the latency caveat. The Gemini latency could be due to me being rate limited on the free tier, I didn't explore it for this study as the case amount(30) was small enough for me to not be bothered.

## Failure modes

Aggregate metrics tell you whether v1 improved on v0, but they don't tell you why. Below are three real v0 failures, one per Act-1 gap (date, hallucination, type), each with the real transcript and the real v0 output from the frozen snapshot. These are the cases that drove the v1 prompt changes.

### Date: "before {weekday}" read as the weekday itself

- **Transcript (memo_006):** "Okay, three things. Dentist appointment is confirmed for Tuesday at 3 p.m. Remind me to uh pay the credit card bill before Friday. And I still need to buy a birthday card for mom."
- **Ground truth:** pay the credit card bill is due by end of Thursday ("before Friday" means end of the previous weekday); the dentist event is on the correct upcoming Tuesday (2026-06-02).
- **v0 output (Anthropic):** set the bill due date to Friday 2026-05-29 (the day named, not the day before), and resolved the bare "Tuesday" to 2026-05-26, a week early. Both date fields landed outside the ground-truth window.
- **Diagnosis:** the model read "before Friday" as "on Friday" and anchored the bare weekday to the wrong week. v0 date accuracy on this case was 0.417.
- **Fix in v1:** explicit weekday rules ("before {weekday}" = end of day on the previous weekday) and current-date anchoring in the prompt.

### Hallucination: a note forced into a typed item

- **Transcript (memo_004):** "Just a note to myself, the back door lock is sticking again. Not urgent, but good to be aware of."
- **Ground truth:** one entry in `notes`, zero action items.
- **v0 output (OpenAI):** a Reminder ("The back door lock is sticking again") with no time, and an empty `notes` array.
- **Diagnosis:** a purely awareness-only remark got forced into a typed slot, inventing an action item that does not exist. This is exactly the pattern the `notes` field exists to absorb, and with no ground-truth item to match, it scores as a 100% hallucination on this case.
- **Fix in v1:** hardened prompt guidance to route awareness-only remarks to `notes` instead of a Reminder or Todo.

### Type: "remind me to {action}" classified as a Reminder

- **Transcript (memo_008):** "I gotta get that proposal sent to the client next Thursday at the latest. Remind me on Wednesday so I have time to review it first."
- **Ground truth:** two Todos (send the proposal by Thursday; review the proposal by Wednesday).
- **v0 output (Anthropic):** the send is a Todo (correct), but the review is emitted as a Reminder.
- **Diagnosis:** the surface phrasing "remind me on Wednesday" pulled the model toward a Reminder, but the underlying intent is an action (review), which the labeling guide classifies as a Todo. One of the two items got the wrong type, so v0 type accuracy on this case was 0.500.
- **Fix in v1:** the type rule ("remind me to {action verb}" is a Todo; awareness-only is a Reminder) was made explicit in the prompt.

## Limitations

Honest caveats on what this study does and doesn't measure.

- **v0 prompt and labeling guide were co-designed.** The labeling rules in [`docs/labeling-guide.md`](./docs/labeling-guide.md) and the v0 system prompt were written together, after the 22 transcript topics were chosen. v0 is therefore not a blind baseline; it knows the schema conventions the test set uses. The v0 → v1 delta is still meaningful (both versions sit on the same rule baseline), but absolute v0 scores should not be read as "what an off-the-shelf agent would do on novel data." A future iteration would write the prompt without sight of the test set.
- **Small N.** 24 visible + 6 held-out test cases. Per-metric 95% bootstrap CIs (per [ADR-005](./docs/adr/005-bootstrap-confidence-intervals.md)) will be wide, especially on the held-out split. A held-out CI that straddles zero is not on its own evidence of failure to generalize.
- **English only, single speaker.** All self-recorded transcripts come from one person, in similar acoustic environments, in English. Accent robustness, multilingual extraction, and noisy-background performance are out of scope.
- **Single labeler.** Inter-annotator agreement is not measured. A second labeler might reasonably disagree on borderline cases (vague-time bounds, Reminder vs Todo on ambiguous utterances).
- **Audio is not in the public repo.** Out of privacy and size considerations. The canonical artifact is the JSON ground truth in `data/transcripts/`; the recording-side methodology lives in [`docs/labeling-guide.md`](./docs/labeling-guide.md). Bit-for-bit reproduction requires re-recording from the methodology.
- **Provider snapshot, not provider capability.** All scores are conditional on the specific model versions used at run time. Provider behavior drifts; results six months from now would differ even with identical code.
- **The prompt's date/time rules wouldn't scale as-is.** v1 teaches the model fixed time mappings directly in the prompt (e.g. "afternoon" -> 3pm, "before Friday" -> Thursday end of day). That's the right call for a benchmark measuring the model's raw single-call extraction, but in a real product those rules belong in code, not in an ever-growing prompt. The reasoning, and the signal for when prompt-encoded rules start to hurt, is in [`docs/prompt-scaling-thoughts.md`](./docs/prompt-scaling-thoughts.md).
- **The per-case diagnostic shows where to look, but its fixes can still be wrong.** The same read-the-data-then-change-the-prompt loop drove both versions. It got v1 right (the type and hallucination fixes worked), but got v2 wrong: we were confident that deleting a weekday rule would fix the dates, and instead every weekday case got worse. The data points at problems well, but a fix that looks right on paper can still fail once you run it. Full write-up in [`docs/v2-failure-analysis.md`](./docs/v2-failure-analysis.md).
- **Negation was solved from v0, so its metric carries no iteration signal.** The test set deliberately over-invested in negation (4 of the 8 synthetic cases are explicit retractions, plus memo_021 / memo_022 in the self-recorded set) expecting it to be a failure mode. It wasn't: Negation Handling sits at ~0.995 at v0 and 1.000 at v1/v2 with a zero-width CI. That is a legitimate finding (negation is easy for current models), but it means the negation investment produced no before/after story. It is reported as a single headline statement rather than a leaderboard iteration metric.

## Future work

These are the experiments I would run next, in priority order. The first two come straight out of this study's own findings, so they are the most grounded.

### Next experiments (motivated by the results)

- **A bigger, more date-dense test set, sized for resolution.** v2 showed that date accuracy is sample-size-bound at N=30: the effect a single prompt edit produces (~0.03) is smaller than the test set's case-sampling noise (~±0.06), so real date movement is invisible. The fix is more date-bearing cases, planned for statistical power rather than just "more cases." As a rough planning heuristic, the bootstrap CI shrinks with about 1/sqrt(N), so roughly 4x the date-bearing cases would halve the interval to ~±0.03, and you would want more than that to resolve a 0.03 effect with confidence (treat these as order-of-magnitude guides, not promises). Stratify the new cases by memo size (single item, 3 to 5 items, many) and by date type (weekday deadlines, vague time-of-day, relative offsets like "in two weeks", absolute dates), so a movement can be attributed to a specific sub-pattern instead of disappearing into the aggregate. Done well, this turns the benchmark into a sharper judge of date specifically.
- **A detection-focused iteration (deferred from v2).** v1 cut hallucinations but also dropped 10 real items (see [the v1 detection retrospective](./docs/v1-detection-retrospective.md)); v2 spent its single edit on date and left detection alone. The hard part, and the reason it did not fit a one-line v2 change, is that detection and hallucination read off the same matcher pool, so v1 moved both with one knob (33 fewer items = 23 fewer false positives + 10 fewer true positives). A real detection fix has to decouple them: recover the dropped true positives without re-adding the false positives. That likely means a more surgical change than a single prompt instruction, for example separating "suppress non-actionable text" from "never drop a real action", or a two-pass extract-then-filter step.

### Productionization

Out of scope for this study, but the obvious path to a real product:

- Real-time audio input via Whisper streaming, instead of pre-recorded transcripts.
- Production tracing and observability (for example Langfuse) on live extractions.
- A CI job that runs the eval suite on every pull request, so prompt changes are gated by the metrics.
- Packaging the agent as an installable library.
- Multi-language support (the current study is English only).
- Domain-specific test sets (medical, legal, meeting notes), each with its own labeling guide.
- A human-in-the-loop review interface for eval results and disagreements.

## Engineering Notes
- **`pip install -e .` (editable install):** links the package to your local `src/` so code changes reflect immediately without reinstalling. Use this during development. Use `pip install .` (no `-e`) when you want a static install, like in a Docker image or CI.
- If you're using a virtual environment, make sure VS Code's Python interpreter is pointing to that venv (Cmd+Shift+P > "Python: Select Interpreter").
