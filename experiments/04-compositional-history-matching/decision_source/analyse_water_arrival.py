"""Diagnose water-cut threshold arrival in complete runs while retaining the original selection metric."""

import argparse
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="+")
args = parser.parse_args()
thresholds = [0.001, 0.01, 0.05, 0.1]
result = {
    "definition": (
        "For each well use OPEN report times with positive historical liquid rate. "
        "Report the first day water cut reaches a specified threshold, without "
        "interpolation or a persistence requirement. A missing crossing is null."
    ),
    "purpose": (
        "Used to diagnose water arrival and spatial-edit hypotheses. The window "
        "introduces no new ranking weights and provides no blind-test evidence."
    ),
    "case": {},
}
for name in args.names:
    m = pd.read_csv(ROOT / "runs" / name / "matched_oil_water.csv")
    active = m[m.primary].copy()
    active["observed_water_cut"] = active.qw_obs / (active.qo_obs + active.qw_obs)
    active["simulated_water_cut"] = active.qw_sim / (active.qo_sim + active.qw_sim)
    wells = {}
    for well, d in active.groupby("well"):
        d = d.sort_values("end_days")
        crossing = {}
        for threshold in thresholds:
            item = {}
            for column in ["observed_water_cut", "simulated_water_cut"]:
                selected = d.loc[d[column] >= threshold, "end_days"]
                item[column] = float(selected.iloc[0]) if len(selected) else None
            crossing[f"{threshold * 100:g}%"] = item
        wells[well] = crossing
    result["case"][name] = wells
path = ROOT / "results/water_arrival_diagnostics.json"
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(path)
