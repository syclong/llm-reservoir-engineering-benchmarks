"""Plot simulated production and original observations at their report times without interpolating missing values."""

import argparse
import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SOURCE_DIR = Path(__file__).resolve().parent
ARCHIVE = SOURCE_DIR.parent
RUNS = SOURCE_DIR / "runs" if (SOURCE_DIR / "runs").is_dir() else ARCHIVE / "evidence"
parser = argparse.ArgumentParser()
parser.add_argument("best")
parser.add_argument("--baseline", default="baseline_tuned")
default_output = (
    SOURCE_DIR / "results" if RUNS.parent == SOURCE_DIR else ARCHIVE / "results"
)
parser.add_argument("--output-dir", type=Path, default=default_output)
args = parser.parse_args()
out = args.output_dir
out.mkdir(parents=True, exist_ok=True)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.unicode_minus": False,
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "savefig.facecolor": "white",
    }
)
baseline = pd.read_csv(RUNS / args.baseline / "matched_oil_water.csv")
best = pd.read_csv(RUNS / args.best / "matched_oil_water.csv")
wells = sorted(baseline.well.unique())
fig, axes = plt.subplots(len(wells), 3, figsize=(16, 17), layout="constrained")
columns = [
    ("qo", "Oil rate (m³/d)", 1),
    ("qw", "Water rate (m³/d)", 1),
    ("watercut", "Water cut (%)", 100),
]
for i, well in enumerate(wells):
    base = baseline[baseline.well == well]
    fit = best[best.well == well]
    for j, (key, label, scale) in enumerate(columns):
        ax = axes[i, j]
        ax.scatter(
            base.end_days,
            base[key + "_obs"] * scale,
            color="#202a35",
            s=8,
            label="Observed",
            zorder=3,
        )
        ax.plot(
            base.end_days,
            base[key + "_sim"] * scale,
            color="#a9b3bf",
            lw=1.2,
            label="Original-field baseline",
        )
        ax.plot(
            fit.end_days,
            fit[key + "_sim"] * scale,
            color="#007b80",
            lw=1.5,
            label="Model field edits",
        )
        ax.set_title(well + " · " + label, loc="left", fontsize=11)
        ax.grid(alpha=0.16)
        if i == len(wells) - 1:
            ax.set_xlabel("Days since history start")
axes[0, 0].legend(frameon=False, fontsize=9)
fig.suptitle(
    "Oil and water history match with the original JutulDarcy simulator and model-specified field edits",
    fontsize=17,
)
fig.savefig(out / "six_well_history_match.png", dpi=180)
plt.close(fig)
field_base = pd.read_csv(RUNS / args.baseline / "matched_field_oil_water.csv")
field_best = pd.read_csv(RUNS / args.best / "matched_field_oil_water.csv")
fig, axes = plt.subplots(2, 1, figsize=(14, 8), layout="constrained", sharex=True)
for ax, (key, title) in zip(
    axes, [("qo", "Field oil rate (FOPR)"), ("qw", "Field water rate (FWPR)")]
):
    ax.scatter(
        field_base.end_days,
        field_base[key + "_obs"] / 1000,
        color="#202a35",
        s=10,
        label="Observed",
        zorder=3,
    )
    ax.plot(
        field_base.end_days,
        field_base[key + "_sim"] / 1000,
        color="#a9b3bf",
        lw=1.2,
        label="Original-field baseline",
    )
    ax.plot(
        field_best.end_days,
        field_best[key + "_sim"] / 1000,
        color="#007b80",
        lw=1.5,
        label="Model field edits",
    )
    ax.set_title(title, loc="left")
    ax.set_ylabel("Thousand m³/d")
    ax.grid(alpha=0.16)
axes[0].legend(frameon=False)
axes[-1].set_xlabel("Days since history start")
fig.suptitle("Field oil and water history match", fontsize=16)
fig.savefig(out / "field_oil_water_history.png", dpi=180)
plt.close(fig)
scores = [
    json.loads((RUNS / n / "oil_water_score.json").read_text(encoding="utf-8"))
    for n in [args.baseline, args.best]
]
fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), layout="constrained")
for ax, (key, title) in zip(
    axes,
    [
        ("oil_rmse_m3_day", "Oil-rate RMSE (m³/d)"),
        ("water_rmse_m3_day", "Water-rate RMSE (m³/d)"),
        ("water_cut_rmse_percentage_points", "Water-cut RMSE (percentage points)"),
    ],
):
    for k, (s, color, name) in enumerate(
        zip(
            scores,
            ["#a9b3bf", "#007b80"],
            ["Original-field baseline", "Model field edits"],
        )
    ):
        ax.bar(
            [i + (k - 0.5) * 0.36 for i in range(len(wells))],
            [s["full_period"]["per_well"][w][key] for w in wells],
            width=0.34,
            color=color,
            label=name,
        )
    ax.set_xticks(range(len(wells)), wells)
    ax.set_title(title, loc="left")
    ax.grid(axis="y", alpha=0.16)
axes[0].legend(frameon=False)
fig.savefig(out / "well_rmse_comparison.png", dpi=180)
plt.close(fig)
print(out)
