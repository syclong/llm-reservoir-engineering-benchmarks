"""Compare the explicitly identified common partial window. Full-period scores require complete runs."""

import argparse
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from compositional_tools import history

parser = argparse.ArgumentParser()
parser.add_argument(
    "diagnostics", nargs="+", help="name=directory containing read-only diagnostics"
)
parser.add_argument("--output", required=True)
args = parser.parse_args()
obs = history().query("kind == 'producer'").copy()
obs["end_days"] = obs.end_days.round(6)
frames = {}
for argument in args.diagnostics:
    name, folder = argument.split("=", 1)
    path = ROOT / folder
    raw = pd.read_csv(path / "well_results_si.csv")
    raw = (
        raw[raw.variable.isin(["orat", "wrat"])]
        .pivot(index=["time_days", "well"], columns="variable", values="value_si")
        .reset_index()
    )
    raw["end_days"] = raw.time_days.round(6)
    raw["qo_sim"] = -86400 * raw.orat
    raw["qw_sim"] = -86400 * raw.wrat
    matched = obs.merge(raw, on=["end_days", "well"], validate="one_to_one")
    matched["primary"] = (matched.status == "OPEN") & (
        matched.qo_obs + matched.qw_obs > 1e-6
    )
    matched.to_csv(
        path / "matched_oil_water_partial.csv", index=False, encoding="utf-8"
    )
    frames[name] = matched
cutoff = min(frame.end_days.max() for frame in frames.values())
keys = None
for frame in frames.values():
    current = set(
        map(tuple, frame.loc[frame.end_days <= cutoff, ["end_days", "well"]].to_numpy())
    )
    if keys is None:
        keys = current
    else:
        assert keys == current, (
            "Common report times are incomplete. Only identical historical windows can be compared."
        )
result = {
    "partial_window_only": True,
    "common_end_day": float(cutoff),
    "history_duration_days": float(obs.end_days.max()),
    "statistical_definition": (
        "Well statistics use OPEN observations with positive historical liquid rate. "
        "Field diagnostics report both all report times and producing times; the "
        "formal full-period field score uses producing times."
    ),
    "comparison": {},
}
for name, frame in frames.items():
    frame = frame[frame.end_days <= cutoff]
    frames[name] = frame
    active = frame[frame.primary]
    metrics = {}
    for well, group in active.groupby("well"):
        error = (
            group[["qo_sim", "qw_sim"]].to_numpy()
            - group[["qo_obs", "qw_obs"]].to_numpy()
        )
        metrics[well] = {
            "valid_samples": len(group),
            "oil_rmse_m3_day": float(np.sqrt(np.mean(error[:, 0] ** 2))),
            "water_rmse_m3_day": float(np.sqrt(np.mean(error[:, 1] ** 2))),
        }
    field = frame.groupby("end_days")[["qo_obs", "qw_obs", "qo_sim", "qw_sim"]].sum()
    field_error = (
        field[["qo_sim", "qw_sim"]].to_numpy() - field[["qo_obs", "qw_obs"]].to_numpy()
    )
    result["comparison"][name] = {
        "per_well": metrics,
        "field_oil_rmse_m3_day": float(np.sqrt(np.mean(field_error[:, 0] ** 2))),
        "field_water_rmse_m3_day": float(np.sqrt(np.mean(field_error[:, 1] ** 2))),
    }
    producing = (field.qo_obs + field.qw_obs).to_numpy() > 1e-6
    result["comparison"][name]["field_producing_oil_rmse_m3_day"] = float(
        np.sqrt(np.mean(field_error[producing, 0] ** 2))
    )
    result["comparison"][name]["field_producing_water_rmse_m3_day"] = float(
        np.sqrt(np.mean(field_error[producing, 1] ** 2))
    )
out = ROOT / "results"
out.mkdir(exist_ok=True)
(out / (args.output + ".json")).write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "axes.unicode_minus": False,
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
    }
)
wells = sorted(obs.well.unique())
fig, axes = plt.subplots(len(wells), 2, figsize=(14, 15), layout="constrained")
colors = ["#b2b9c4", "#008080", "#b7772a", "#704ca0"]
for row, well in enumerate(wells):
    observed = obs[(obs.well == well) & (obs.end_days <= cutoff)]
    for col, (key, label) in enumerate([("qo", "Oil rate"), ("qw", "Water rate")]):
        ax = axes[row, col]
        ax.scatter(
            observed.end_days,
            observed[key + "_obs"],
            s=9,
            color="#25313e",
            label="Observed",
            zorder=4,
        )
        for (name, frame), color in zip(frames.items(), colors):
            group = frame[frame.well == well]
            ax.plot(
                group.end_days, group[key + "_sim"], color=color, label=name, lw=1.3
            )
        ax.set_title(f"{well} · {label} (m³/d)", loc="left")
        ax.grid(alpha=0.18)
        if row == len(wells) - 1:
            ax.set_xlabel("Days since history start")
axes[0, 0].legend(frameon=False)
fig.suptitle(
    f"Oil and water response through day {cutoff:g} of the 2,891-day history (partial runs)",
    fontsize=15,
)
fig.savefig(out / (args.output + ".png"), dpi=150)
plt.close(fig)
fig, axes = plt.subplots(2, 1, figsize=(13, 7), layout="constrained", sharex=True)
observed_field = (
    obs[obs.end_days <= cutoff].groupby("end_days")[["qo_obs", "qw_obs"]].sum()
)
for ax, (key, label) in zip(
    axes, [("qo", "Field oil rate (FOPR)"), ("qw", "Field water rate (FWPR)")]
):
    ax.scatter(
        observed_field.index,
        observed_field[key + "_obs"],
        s=10,
        color="#25313e",
        label="Observed",
        zorder=4,
    )
    for (name, frame), color in zip(frames.items(), colors):
        field = frame.groupby("end_days")[["qo_sim", "qw_sim"]].sum()
        ax.plot(field.index, field[key + "_sim"], color=color, label=name, lw=1.3)
    ax.set_title(label, loc="left")
    ax.set_ylabel("m³/d")
    ax.grid(alpha=0.18)
axes[0].legend(frameon=False)
axes[-1].set_xlabel("Days since history start")
fig.suptitle(f"Field response through day {cutoff:g} (partial history)", fontsize=15)
fig.savefig(out / (args.output + "_field.png"), dpi=150)
plt.close(fig)
print(json.dumps(result, ensure_ascii=False, indent=2))
