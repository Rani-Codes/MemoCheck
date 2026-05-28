-- 001_init: initial schema for MemoCheck eval persistence.
--
-- One row per (agent_version, provider, model, test_case, attempt) in test_runs.
-- One row per (test_run, metric) in metric_scores, carrying raw numerator and
-- denominator so the dashboard can micro-average across cases:
--
--   SELECT metric_name,
--          SUM(numerator)::float / NULLIF(SUM(denominator), 0) AS score
--   FROM metric_scores
--   GROUP BY metric_name;
--
-- score / passed are denormalized convenience columns; they may be NULL when
-- denominator = 0 (the metric is undefined for that case, e.g. Detection on a
-- case with an empty ground-truth pool).

CREATE TABLE IF NOT EXISTS test_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    agent_version TEXT NOT NULL,            -- "v0" | "v1" | "v2"
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    test_case_id TEXT NOT NULL,
    attempt INT NOT NULL,                   -- 1..3 per (provider, case)
    transcript TEXT NOT NULL,
    expected_output JSONB NOT NULL,
    actual_output JSONB,
    raw_llm_response TEXT,
    schema_valid BOOLEAN NOT NULL,
    latency_ms INT,
    cost_usd NUMERIC(10, 6),
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS metric_scores (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    test_run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    numerator INT NOT NULL,
    denominator INT NOT NULL,
    score NUMERIC(5, 4),                    -- NULL when denominator = 0
    threshold NUMERIC(5, 4),
    passed BOOLEAN,                          -- NULL when score is NULL
    explanation TEXT,
    UNIQUE (test_run_id, metric_name)
);

CREATE INDEX IF NOT EXISTS test_runs_agent_provider_idx
    ON test_runs (agent_version, provider);
CREATE INDEX IF NOT EXISTS test_runs_case_idx
    ON test_runs (agent_version, provider, test_case_id);
CREATE INDEX IF NOT EXISTS test_runs_created_idx
    ON test_runs (created_at DESC);
CREATE INDEX IF NOT EXISTS metric_scores_run_idx
    ON metric_scores (test_run_id);
