#!/usr/bin/env python3
"""Generate static result charts (PNG + SVG) for the README and dashboard.

Deterministic and token-free: reads only the committed report JSONs in
``data/results/`` and writes images to ``dashboard/charts/``. Run with the
project venv:

    .venv/bin/python scripts/build_charts.py

PNG is high-DPI for the README (GitHub always renders it); SVG is vector for
the dashboard. Both report files use the version-agnostic ``baseline`` /
``candidate`` keys.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import seaborn as sns  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "data" / "results"
OUT = ROOT / "dashboard" / "charts"

NAMES = {
    "detection_rate": "Detection",
    "hallucination_rate": "Hallucination",
    "type_accuracy": "Type",
    "date_accuracy": "Date",
    "attribution_accuracy": "Attribution",
    "negation_handling": "Negation",
    "schema_adherence": "Schema",
}
# every metric is "higher is better" except the hallucination rate
HIGHER_BETTER = {m: (m != "hallucination_rate") for m in NAMES}

WIN = "#2e7d32"
COST = "#c62828"
FLAT = "#9e9e9e"
V0 = "#90a4ae"
V1 = "#1565c0"


def style() -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 120,
            "savefig.dpi": 200,
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.titleweight": "bold",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "figure.constrained_layout.use": True,
        }
    )


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}")
    plt.close(fig)
    print("wrote", name, "(png, svg)")


def load(fname: str) -> dict:
    return json.loads((RESULTS / fname).read_text())


def chart_before_after(d: dict) -> None:
    metrics = [
        "detection_rate",
        "type_accuracy",
        "date_accuracy",
        "attribution_accuracy",
        "hallucination_rate",
        "negation_handling",
    ]
    s = d["slices"]["all"]
    v0 = [s[m]["baseline"] for m in metrics]
    v1 = [s[m]["candidate"] for m in metrics]
    x = np.arange(len(metrics))
    w = 0.38
    fig, ax = plt.subplots(figsize=(9.5, 5.0))
    b0 = ax.bar(x - w / 2, v0, w, label="v0", color=V0)
    b1 = ax.bar(x + w / 2, v1, w, label="v1", color=V1)
    ax.set_xticks(x)
    ax.set_xticklabels([NAMES[m] for m in metrics])
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("rate (micro-averaged, all 30 cases)")
    ax.set_title("v0 vs v1, all 30 cases")
    for b in list(b0) + list(b1):
        ax.annotate(
            f"{b.get_height():.3f}",
            (b.get_x() + b.get_width() / 2, b.get_height()),
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax.legend(loc="lower left")
    fig.supxlabel(
        "Higher is better, except Hallucination where lower is better.",
        fontsize=9,
        color="#555",
    )
    save(fig, "before_after")


def chart_improvement_ci(d: dict) -> None:
    metrics = [
        "type_accuracy",
        "hallucination_rate",
        "detection_rate",
        "date_accuracy",
        "attribution_accuracy",
        "negation_handling",
    ]
    s = d["slices"]["all"]
    rows = []
    for m in metrics:
        delta, lo, hi = s[m]["delta"], s[m]["ci_low"], s[m]["ci_high"]
        if HIGHER_BETTER[m]:
            imp, ilo, ihi = delta, lo, hi
        else:  # flip so "positive = better" holds for hallucination too
            imp, ilo, ihi = -delta, -hi, -lo
        rows.append((NAMES[m], imp, ilo, ihi))
    rows.sort(key=lambda r: r[1])

    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    ax.axvline(0, color="#333", lw=1)
    for yi, (_, imp, ilo, ihi) in enumerate(rows):
        color = WIN if ilo > 0 else COST if ihi < 0 else FLAT
        ax.plot([ilo, ihi], [yi, yi], color=color, lw=3, solid_capstyle="round")
        ax.scatter([imp], [yi], color=color, zorder=3, s=45)
        ax.annotate(
            f"{imp:+.3f}",
            (imp, yi),
            textcoords="offset points",
            xytext=(0, 9),
            ha="center",
            fontsize=8,
        )
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in rows])
    ax.set_xlabel("v0 to v1 improvement (oriented so positive = better)")
    ax.set_title("v0 to v1 improvement with 95% bootstrap CI")
    ax.legend(
        handles=[
            Patch(color=WIN, label="CI excludes 0 (win)"),
            Patch(color=FLAT, label="CI straddles 0"),
            Patch(color=COST, label="significant cost"),
        ],
        loc="lower right",
        fontsize=8,
    )
    save(fig, "improvement_ci")


def chart_provider_heatmap(d: dict) -> None:
    provs = sorted(d["by_provider"].keys())
    metrics = [
        "type_accuracy",
        "detection_rate",
        "date_accuracy",
        "attribution_accuracy",
        "negation_handling",
    ]
    matrix = np.array(
        [[d["by_provider"][p][m]["candidate"] for m in metrics] for p in provs]
    )
    fig, ax = plt.subplots(figsize=(8.0, 4.0))
    sns.heatmap(
        matrix,
        annot=True,
        fmt=".3f",
        cmap="RdYlGn",
        vmin=0.6,
        vmax=1.0,
        xticklabels=[NAMES[m] for m in metrics],
        yticklabels=[p.capitalize() for p in provs],
        cbar_kws={"label": "v1 score"},
        linewidths=0.5,
        linecolor="white",
        ax=ax,
    )
    ax.set_title("v1 scores by provider (higher is better)")
    fig.supxlabel(
        "Color 0.6 to 1.0; cell labels are exact. "
        "Hallucination is in the before/after chart.",
        fontsize=9,
        color="#555",
    )
    save(fig, "provider_heatmap")


def chart_per_category(d: dict) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.5))
    for ax, m in zip(axes, ["type_accuracy", "hallucination_rate"]):
        items = []
        for cat, mets in d["by_category"].items():
            if m not in mets:
                continue
            delta = mets[m]["delta"]
            if delta is None or abs(delta) < 1e-9:
                continue
            imp = delta if HIGHER_BETTER[m] else -delta
            items.append((cat, imp, mets[m]["n_cases"]))
        items.sort(key=lambda r: r[1])
        y = np.arange(len(items))
        colors = [WIN if imp > 0 else COST for _, imp, _ in items]
        ax.barh(y, [imp for _, imp, _ in items], color=colors)
        ax.axvline(0, color="#333", lw=1)
        ax.set_yticks(y)
        ax.set_yticklabels(
            [f"{c} (n={n})" + (" *" if n == 1 else "") for c, _, n in items]
        )
        ax.set_title(f"{NAMES[m]} v0 to v1 by category\n(positive = better)")
        ax.set_xlabel("improvement")
    fig.supxlabel(
        "* single-case category (n=1): anecdotal, no CI. "
        "Only categories with a nonzero change are shown.",
        fontsize=8,
        color="#555",
    )
    save(fig, "per_category_deltas")


def chart_date_trajectory(d01: dict, d12: dict) -> None:
    s01 = d01["slices"]["all"]["date_accuracy"]
    s12 = d12["slices"]["all"]["date_accuracy"]
    xs = ["v0", "v1", "v2"]
    vals = [s01["baseline"], s01["candidate"], s12["candidate"]]
    fig, ax = plt.subplots(figsize=(7.0, 4.8))
    ax.plot(xs, vals, marker="o", color=V1, lw=2.5, markersize=9)
    for x, v in zip(xs, vals):
        ax.annotate(
            f"{v:.3f}",
            (x, v),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            fontsize=10,
        )
    ax.set_ylim(0.6, 0.9)
    ax.set_ylabel("date accuracy (all 30, micro-averaged)")
    ax.set_title("Date accuracy stays flat across versions")
    fig.supxlabel(
        "Sample-size-bound at N=30; the v1 to v2 95% CI straddles zero.",
        fontsize=9,
        color="#555",
    )
    save(fig, "date_trajectory")


def main() -> None:
    style()
    d01 = load("v0_vs_v1.json")
    d12 = load("v1_vs_v2.json")
    chart_before_after(d01)
    chart_improvement_ci(d01)
    chart_provider_heatmap(d01)
    chart_per_category(d01)
    chart_date_trajectory(d01, d12)
    print("done ->", OUT)


if __name__ == "__main__":
    main()
