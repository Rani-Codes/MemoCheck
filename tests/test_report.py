import json

from memocheck.evals.report import (
    MetricRecord,
    bootstrap_delta_ci,
    build_report,
    micro_average,
    parse_categories,
    report_to_payload,
    responded,
)


def test_micro_average_micro_averages_across_cases():
    # pooled: (2+1) matched / (3+1) relevant = 0.75, not the macro mean of ratios
    assert micro_average([(2, 3), (1, 1)]) == 0.75


def test_micro_average_undefined_when_pool_empty():
    assert micro_average([(0, 0), (0, 0)]) is None


def test_bootstrap_zero_variance_collapses_ci_to_point_delta():
    # Every case identical, v1 uniformly perfect: every resample yields the same
    # micro-average, so the delta has no spread and the CI is a point.
    v0 = {"a": (1, 2), "b": (1, 2)}
    v1 = {"a": (2, 2), "b": (2, 2)}
    r = bootstrap_delta_ci(v0, v1, ["a", "b"], n_resamples=200, seed=0)
    assert r.baseline == 0.5
    assert r.candidate == 1.0
    assert r.delta == 0.5
    assert r.ci_low == 0.5
    assert r.ci_high == 0.5
    assert r.n_cases == 2


def test_bootstrap_is_deterministic_and_brackets_point_delta():
    v0 = {"a": (0, 1), "b": (1, 1), "c": (1, 2)}
    v1 = {"a": (1, 1), "b": (1, 1), "c": (2, 2)}
    ids = ["a", "b", "c"]
    r1 = bootstrap_delta_ci(v0, v1, ids, n_resamples=1000, seed=7)
    r2 = bootstrap_delta_ci(v0, v1, ids, n_resamples=1000, seed=7)
    assert (r1.ci_low, r1.ci_high) == (r2.ci_low, r2.ci_high)  # same seed -> same CI
    assert r1.ci_low < r1.ci_high  # genuine spread with non-degenerate data
    assert r1.ci_low <= r1.delta <= r1.ci_high  # CI brackets the point delta


def test_bootstrap_undefined_when_all_denominators_zero():
    v0 = {"a": (0, 0)}
    v1 = {"a": (0, 0)}
    r = bootstrap_delta_ci(v0, v1, ["a"])
    assert r.baseline is None and r.candidate is None and r.delta is None
    assert r.ci_low is None and r.ci_high is None


def test_responded_counts_clean_output_and_validation_failures():
    # Schema Adherence denominator = runs where the model actually responded.
    assert responded(None) is True  # clean success
    assert responded(
        "1 validation error for ExtractedMemo\ntodos.0.due_date: invalid"
    ) is True  # model responded, just with invalid JSON


def test_responded_excludes_network_and_infra_errors():
    assert (
        responded("RateLimitError: litellm.RateLimitError: Rate limit reached")
        is False
    )
    assert responded("APIConnectionError: connection reset by peer") is False
    assert responded("Timeout: request timed out after 60s") is False


def test_build_report_assembles_slices_metrics_and_breakdowns():
    recs = [
        MetricRecord("v0", "p", "detection_rate", "c1", 1, 2),
        MetricRecord("v1", "p", "detection_rate", "c1", 2, 2),
        MetricRecord("v0", "p", "detection_rate", "c2", 1, 2),
        MetricRecord("v1", "p", "detection_rate", "c2", 2, 2),
        MetricRecord("v0", "p", "detection_rate", "c3", 0, 2),
        MetricRecord("v1", "p", "detection_rate", "c3", 1, 2),
    ]
    rep = build_report(
        recs,
        baseline="v0",
        candidate="v1",
        categories={"c1": "alpha", "c2": "alpha", "c3": "beta"},
        held_out_ids={"c3"},
        n_resamples=200,
        seed=0,
    )

    assert rep.metrics == ["detection_rate"]

    # visible = c1,c2: baseline = (1+1)/(2+2) = 0.5, candidate = 1.0, delta = 0.5
    vis = rep.slices["visible"]["detection_rate"]
    assert (vis.baseline, vis.candidate, vis.delta, vis.n_cases) == (0.5, 1.0, 0.5, 2)

    # held_out = c3: baseline = 0/2 = 0.0, candidate = 1/2 = 0.5
    ho = rep.slices["held_out"]["detection_rate"]
    assert (ho.baseline, ho.candidate, ho.n_cases) == (0.0, 0.5, 1)

    # all = 3 cases pooled
    al = rep.slices["all"]["detection_rate"]
    assert al.n_cases == 3
    assert al.baseline == 2 / 6 and al.candidate == 5 / 6

    # per-category point table (all-30): alpha = c1,c2
    assert rep.by_category["alpha"]["detection_rate"].delta == 0.5
    # per-provider point table (all-30): provider p over all 3 cases
    assert rep.by_provider["p"]["detection_rate"].candidate == 5 / 6


def test_build_report_pools_providers_and_attaches_ci_to_slices():
    recs = [
        MetricRecord("v0", "p", "detection_rate", "c1", 1, 2),
        # same case, 2nd provider
        MetricRecord("v0", "q", "detection_rate", "c1", 0, 2),
        MetricRecord("v1", "p", "detection_rate", "c1", 2, 2),
        MetricRecord("v1", "q", "detection_rate", "c1", 1, 2),
        MetricRecord("v0", "p", "detection_rate", "c2", 1, 1),
        MetricRecord("v0", "q", "detection_rate", "c2", 0, 1),
        MetricRecord("v1", "p", "detection_rate", "c2", 1, 1),
        MetricRecord("v1", "q", "detection_rate", "c2", 1, 1),
    ]
    rep = build_report(
        recs, baseline="v0", candidate="v1",
        categories={"c1": "a", "c2": "a"}, held_out_ids=set(),
        n_resamples=300, seed=1,
    )

    al = rep.slices["all"]["detection_rate"]
    assert al.baseline == 2 / 6  # (1+0+1+0) / (2+2+1+1), pooled across providers
    assert al.candidate == 5 / 6  # (2+1+1+1) / 6
    assert al.ci_low is not None and al.ci_high is not None
    assert al.ci_low <= al.delta <= al.ci_high

    # the per-provider table keeps providers separate
    assert rep.by_provider["q"]["detection_rate"].baseline == 0.0  # (0+0)/(2+1)
    assert rep.by_provider["p"]["detection_rate"].baseline == 2 / 3  # (1+1)/(2+1)


def test_parse_categories_reads_per_case_table_only():
    md = """
| ID | Split | Category | Eval target |
|---|---|---|---|
| memo_001 | held-out | type_classification | Todo not Reminder |
| synth_008 | visible | negation_false_positive | don't trap |

## Category counts
| Category | Count | Cases |
|---|---|---|
| multi_action | 4 | memo_005, memo_013 |
"""
    cats = parse_categories(md)
    assert cats["memo_001"] == "type_classification"
    assert cats["synth_008"] == "negation_false_positive"
    # the counts table's first column is a category name, not a case id -> ignored
    assert "multi_action" not in cats
    assert len(cats) == 2


def test_report_to_payload_is_json_serializable_with_metadata():
    recs = [
        MetricRecord("v0", "p", "detection_rate", "c1", 1, 2),
        MetricRecord("v1", "p", "detection_rate", "c1", 2, 2),
    ]
    rep = build_report(
        recs, baseline="v0", candidate="v1",
        categories={"c1": "alpha"}, held_out_ids=set(),
        n_resamples=50, seed=0,
    )
    payload = report_to_payload(
        rep,
        baseline="v0",
        candidate="v1",
        generated_at="2026-05-31T00:00:00Z",
        seed=0,
        n_resamples=50,
    )

    json.dumps(payload)  # must not raise
    assert payload["metrics"] == ["detection_rate"]
    assert payload["baseline"] == "v0" and payload["candidate"] == "v1"
    assert payload["generated_at"] == "2026-05-31T00:00:00Z"
    assert payload["seed"] == 0 and payload["n_resamples"] == 50
    assert set(payload["slices"]) == {"visible", "held_out", "all"}
    assert payload["slices"]["all"]["detection_rate"]["delta"] == 0.5
    assert "by_provider" in payload and "by_category" in payload


def test_build_report_is_version_agnostic_for_baseline_candidate():
    # The pipeline must compare any two versions, not just v0/v1, so a v1 -> v2
    # report pulls v1 as baseline and v2 as candidate and exposes them under
    # generic .baseline / .candidate fields.
    recs = [
        MetricRecord("v1", "p", "date_accuracy", "c1", 1, 2),
        MetricRecord("v2", "p", "date_accuracy", "c1", 2, 2),
    ]
    rep = build_report(
        recs,
        baseline="v1",
        candidate="v2",
        categories={"c1": "alpha"},
        held_out_ids=set(),
        n_resamples=100,
        seed=0,
    )
    d = rep.slices["all"]["date_accuracy"]
    assert d.baseline == 0.5  # v1
    assert d.candidate == 1.0  # v2
    assert d.delta == 0.5
    assert rep.by_provider["p"]["date_accuracy"].baseline == 0.5
    assert rep.by_category["alpha"]["date_accuracy"].candidate == 1.0


def test_report_to_payload_records_arbitrary_baseline_candidate():
    recs = [
        MetricRecord("v1", "p", "date_accuracy", "c1", 1, 2),
        MetricRecord("v2", "p", "date_accuracy", "c1", 2, 2),
    ]
    rep = build_report(
        recs,
        baseline="v1",
        candidate="v2",
        categories={"c1": "alpha"},
        held_out_ids=set(),
        n_resamples=50,
        seed=0,
    )
    payload = report_to_payload(
        rep,
        baseline="v1",
        candidate="v2",
        generated_at="2026-06-01T00:00:00Z",
        seed=0,
        n_resamples=50,
    )
    json.dumps(payload)  # must not raise
    assert payload["baseline"] == "v1" and payload["candidate"] == "v2"
    cell = payload["slices"]["all"]["date_accuracy"]
    assert cell["baseline"] == 0.5 and cell["candidate"] == 1.0
