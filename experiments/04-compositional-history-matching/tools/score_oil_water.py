"""Score oil and water production under the revised objective. Report liquid-rate control error for verification."""

import argparse
import json
from pathlib import Path
import sys
import tomllib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from compositional_tools import history

parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument(
    "--run-dir",
    type=Path,
    help="Optional absolute path or path relative to the current directory for rerun results",
)
parser.add_argument(
    "--history-file",
    type=Path,
    help="Optional path to the original HISTORY.inc from the rerun package",
)
args = parser.parse_args()
run = args.run_dir if args.run_dir is not None else ROOT / "runs" / args.name
verified = tomllib.loads((run / "run_validation.toml").read_text(encoding="utf-8"))
hist = history(args.history_file)
obs = hist[hist.kind == "producer"].copy()
if (
    not verified["full_simulation_passed"]
    or abs(verified["simulated_days"] - float(obs.end_days.max())) > 1e-6
):
    raise ValueError("A full oil and water score requires all 2,891 simulation days")
raw = pd.read_csv(run / "well_results_si.csv")
sim = (
    raw[raw.variable.isin(["orat", "wrat"])]
    .pivot(index=["time_days", "well"], columns="variable", values="value_si")
    .reset_index()
)
records = []
for row in obs.to_dict("records"):
    data = sim[sim.well == row["well"]]
    actual = data.loc[(data.time_days - row["end_days"]).abs().idxmin()]
    if abs(float(actual.time_days) - row["end_days"]) > 1e-6:
        raise ValueError("Missing report at the exact end of a historical interval")
    row["qo_sim"] = -float(actual.orat) * 86400
    row["qw_sim"] = -float(actual.wrat) * 86400
    row["ql_obs"] = row["qo_obs"] + row["qw_obs"]
    row["ql_sim"] = row["qo_sim"] + row["qw_sim"]
    row["primary"] = row["status"] == "OPEN" and row["ql_obs"] > 1e-6
    records.append(row)
frame = pd.DataFrame(records)
frame["oil_error"] = frame.qo_sim - frame.qo_obs
frame["water_error"] = frame.qw_sim - frame.qw_obs
frame["watercut_obs"] = frame.qw_obs / frame.ql_obs.replace(0, np.nan)
frame["watercut_sim"] = frame.qw_sim / frame.ql_sim.where(frame.ql_sim > 1e-9)
frame.to_csv(run / "matched_oil_water.csv", index=False, encoding="utf-8")
active = frame[frame.primary]
scales = active.groupby("well").ql_obs.median().clip(lower=1).to_dict()
phase_scales = {
    w: {
        "oil": max(float(d.qo_obs.quantile(0.95)), 1.0),
        "water": max(float(d.qw_obs.quantile(0.95)), 1.0),
    }
    for w, d in active.groupby("well")
}


def metrics(data):
    if data.empty:
        return None
    errors = data[["oil_error", "water_error"]].to_numpy()
    if not np.isfinite(errors).all():
        raise ValueError("Oil or water output contains nonfinite values")
    liquid_scale = np.array([scales[w] for w in data.well])
    normalized = errors / liquid_scale[:, None]
    own_scale = np.array(
        [[phase_scales[w]["oil"], phase_scales[w]["water"]] for w in data.well]
    )
    phase_normalized = errors / own_scale
    fw_error = np.where(data.ql_sim <= 1e-9, 1.0, data.watercut_sim - data.watercut_obs)
    return {
        "valid_samples": len(data),
        "oil_rmse_m3_day": float(np.sqrt(np.mean(errors[:, 0] ** 2))),
        "water_rmse_m3_day": float(np.sqrt(np.mean(errors[:, 1] ** 2))),
        "combined_oil_water_rmse_m3_day": float(np.sqrt(np.mean(errors**2))),
        "combined_oil_water_nrmse_pct_liquid_scale": float(
            100 * np.sqrt(np.mean(normalized**2))
        ),
        "oil_nrmse_pct_oil_p95_scale": float(
            100 * np.sqrt(np.mean(phase_normalized[:, 0] ** 2))
        ),
        "water_nrmse_pct_water_p95_scale": float(
            100 * np.sqrt(np.mean(phase_normalized[:, 1] ** 2))
        ),
        "combined_oil_water_nrmse_pct_separate_phase_scales": float(
            100 * np.sqrt(np.mean(phase_normalized**2))
        ),
        "water_cut_rmse_percentage_points": float(100 * np.sqrt(np.mean(fw_error**2))),
        "liquid_control_rmse_m3_day": float(
            np.sqrt(np.mean((data.ql_sim - data.ql_obs) ** 2))
        ),
        "open_well_zero_simulated_liquid_count": int((data.ql_sim <= 1e-9).sum()),
    }


out = {
    "candidate": args.name,
    "objective": (
        "Full-history field and well oil and water production. BHP and gas rate are "
        "outside the primary score; terminal observations receive no extra weight."
    ),
    "total_history_days": verified["simulated_days"],
    "liquid_scales_by_well": scales,
    "phase_scales_by_well": phase_scales,
}
end = float(obs.end_days.max())
for name, start in [
    ("full_period", -1),
    ("last_365_days", end - 365),
    ("last_180_days", end - 180),
]:
    chosen = active[active.end_days >= start]
    bywell = {w: metrics(data) for w, data in chosen.groupby("well")}
    out[name] = {
        "per_well": bywell,
        "all_active_samples": metrics(chosen),
        "equal_well_nrmse_pct": float(
            np.sqrt(
                np.mean(
                    [
                        m["combined_oil_water_nrmse_pct_liquid_scale"] ** 2
                        for m in bywell.values()
                    ]
                )
            )
        )
        if bywell
        else None,
    }
    out[name]["equal_well_nrmse_pct_separate_phase_scales"] = (
        float(
            np.sqrt(
                np.mean(
                    [
                        m["combined_oil_water_nrmse_pct_separate_phase_scales"] ** 2
                        for m in bywell.values()
                    ]
                )
            )
        )
        if bywell
        else None
    )
field = frame.groupby(["end_days", "start_days"], as_index=False)[
    ["qo_obs", "qw_obs", "qo_sim", "qw_sim", "ql_obs", "ql_sim"]
].sum()
field["oil_error"] = field.qo_sim - field.qo_obs
field["water_error"] = field.qw_sim - field.qw_obs
field.to_csv(run / "matched_field_oil_water.csv", index=False, encoding="utf-8")
field_active = field[field.ql_obs > 1e-6]
field_scale = np.array(
    [
        max(float(field_active.qo_obs.quantile(0.95)), 1.0),
        max(float(field_active.qw_obs.quantile(0.95)), 1.0),
    ]
)
field_errors = field_active[["oil_error", "water_error"]].to_numpy()
field_norm = field_errors / field_scale
out["field_full_period"] = {
    "sample_count": len(field_active),
    "oil_rmse_m3_day": float(np.sqrt(np.mean(field_errors[:, 0] ** 2))),
    "water_rmse_m3_day": float(np.sqrt(np.mean(field_errors[:, 1] ** 2))),
    "oil_nrmse_pct": float(100 * np.sqrt(np.mean(field_norm[:, 0] ** 2))),
    "water_nrmse_pct": float(100 * np.sqrt(np.mean(field_norm[:, 1] ** 2))),
    "combined_oil_water_nrmse_pct_separate_phase_scales": float(
        100 * np.sqrt(np.mean(field_norm**2))
    ),
    "oil_water_p95_scales_m3_day": field_scale.tolist(),
}
out["combined_field_well_nrmse_pct"] = float(
    np.sqrt(
        0.5
        * out["field_full_period"]["combined_oil_water_nrmse_pct_separate_phase_scales"]
        ** 2
        + 0.5 * out["full_period"]["equal_well_nrmse_pct_separate_phase_scales"] ** 2
    )
)
terminal = frame[abs(frame.end_days - end) < 1e-6].copy()
out["last_point"] = {
    w: {
        "status": r["status"],
        "independent_fit_valid": bool(r["primary"]),
        "observed_oil_m3_day": r["qo_obs"],
        "simulated_oil_m3_day": r["qo_sim"],
        "observed_water_m3_day": r["qw_obs"],
        "simulated_water_m3_day": r["qw_sim"],
        "oil_error_m3_day": r["oil_error"],
        "water_error_m3_day": r["water_error"],
    }
    for w, r in terminal.set_index("well").to_dict("index").items()
}
out["valid_last_point_metrics"] = metrics(terminal[terminal.primary])
(run / "oil_water_score.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
