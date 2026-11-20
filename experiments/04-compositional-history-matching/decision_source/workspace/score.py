"""Score at the original historical interval endpoints. Reverse the simulator production sign to obtain positive production rates and retain the original observations."""

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
parser.add_argument("--partial", action="store_true")
args = parser.parse_args()
run = ROOT / "runs" / args.name
record = tomllib.loads((run / "run_validation.toml").read_text(encoding="utf-8"))
if not record["full_simulation_passed"]:
    raise ValueError("A failed simulation cannot be scored")
hist = history()
obs = hist[hist.kind == "producer"].copy()
obs["primary"] = (obs.status == "OPEN") & (obs.qo_obs + obs.qw_obs > 1e-6)
scales = {
    w: {
        "liquid": max(float((d.qo_obs + d.qw_obs).median()), 1.0),
        "gas": max(float(d.qg_obs.median()), 1.0),
    }
    for w, d in obs[obs.primary].groupby("well")
}
sim = pd.read_csv(run / "well_results_si.csv")
variables = {"orat": "qo_sim", "wrat": "qw_sim", "grat": "qg_sim", "bhp": "bhp_sim"}
sim = (
    sim[sim.variable.isin(variables)]
    .pivot(index=["time_days", "well"], columns="variable", values="value_si")
    .reset_index()
)
sim = sim.rename(columns=variables)
for key in ["qo_sim", "qw_sim", "qg_sim"]:
    sim[key] *= -86400.0
sim["bhp_sim"] /= 1e5
end = float(record["simulated_days"])
if args.partial:
    obs = obs[obs.end_days <= end + 1e-6].copy()
elif abs(float(obs.end_days.max()) - end) > 1e-6:
    raise ValueError("Full-period scoring requires the complete original history")
rows = []
for row in obs.to_dict("records"):
    d = sim[sim.well == row["well"]]
    ix = (d.time_days - row["end_days"]).abs().idxmin()
    actual = d.loc[ix]
    if abs(actual.time_days - row["end_days"]) > 1e-6:
        raise ValueError("Missing output at the exact end of an interval")
    rows.append({**row, **{key: float(actual[key]) for key in variables.values()}})
df = pd.DataFrame(rows)
df["ql_obs"] = df.qo_obs + df.qw_obs
df["ql_sim"] = df.qo_sim + df.qw_sim
df["fw_obs"] = df.qw_obs / df.ql_obs.replace(0, np.nan)
df["fw_sim"] = df.qw_sim / df.ql_sim.where(df.ql_sim > 1e-9)
df.to_csv(run / "matched_observations.csv", index=False, encoding="utf-8")


def metrics(d):
    if not np.isfinite(d[list(variables.values())].to_numpy()).all():
        raise ValueError("Simulation output contains nonfinite values")
    noflow = d.ql_sim <= 1e-9
    fw_error = np.where(noflow, 1.0, d.fw_sim - d.fw_obs)
    fw = float(np.sqrt(np.mean(fw_error**2)))
    pressure = float(np.sqrt(np.mean((d.bhp_sim - d.bhp_obs) ** 2)))
    gas_error = np.array(
        [(r.qg_sim - r.qg_obs) / scales[r.well]["gas"] for r in d.itertuples()]
    )
    liquid_error = np.array(
        [(r.ql_sim - r.ql_obs) / scales[r.well]["liquid"] for r in d.itertuples()]
    )
    gas = float(np.sqrt(np.mean(gas_error**2)))
    return {
        "n": len(d),
        "watercut_rmse_pp": fw * 100,
        "producer_bhp_rmse_bar": pressure,
        "gas_nrmse_pct": gas * 100,
        "liquid_nrmse_pct": float(np.sqrt(np.mean(liquid_error**2)) * 100),
        "rate_rmse_m3_day": float(
            np.sqrt(np.mean(np.r_[d.qo_sim - d.qo_obs, d.qw_sim - d.qw_obs] ** 2))
        ),
        "unexpected_zero_flow_points": int(noflow.sum()),
        "balanced_score": float(
            ((fw / 0.05) ** 2 + (gas / 0.1) ** 2 + (pressure / 20) ** 2) / 3
        ),
    }


valid = df[df.primary]
scores = {w: metrics(d) for w, d in valid.groupby("well")}
out = {
    "candidate": args.name,
    "scoring_period": "partial_history" if args.partial else "full_history",
    "through_day": end,
    "producer_metrics": scores,
    "all_valid_sample_metrics": metrics(valid),
    "equal_well_balanced_score": float(
        np.mean([v["balanced_score"] for v in scores.values()])
    ),
    "Injector THP": (
        "Retain THP as recorded in the original input. The simulation has no THP "
        "forward relation, so the fit score excludes THP. THP is distinct from BHP."
    ),
    "scales": scales,
}
(run / "score.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
)
print(json.dumps(out, ensure_ascii=False, indent=2))
