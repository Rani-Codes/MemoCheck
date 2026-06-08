# Run-to-run nondeterminism

A "flip" is a metric score that changed across its 3 temperature-0 attempts on the identical
input. Counts are (version, provider, case) cells, all versions pooled, from the frozen
snapshot (`data/db_snapshot/`).

| provider | date | type | hallucination |
|---|---|---|---|
| openai | 8/83 (9.6%) | 3/86 (3.5%) | 8/87 (9.2%) |
| groq | 4/86 (4.7%) | 0/87 | 0/87 |
| anthropic | 3/86 (3.5%) | 0/87 | 1/88 (1.1%) |
| gemini | 0/87 | 0/87 | 0/87 |
| **all** | **15/342** | **3/347** | **9/349** |

We set temperature to 0 to get consistent outputs, but provider-side serving still produces
different tokens run to run: 15 date, 3 type, and 9 hallucination flips across the run, almost
all OpenAI, with Gemini never flipping.
