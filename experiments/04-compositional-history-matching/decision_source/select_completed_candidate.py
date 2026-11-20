"""Compare complete simulations with the prespecified oil and water objective."""

import argparse
import json
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("names", nargs="+")
args = parser.parse_args()
rows = []
for name in ["baseline_tuned", *dict.fromkeys(args.names)]:
    assert Path(name).name == name and name not in {".", ".."}
    run = ROOT / "runs" / name
    v = tomllib.loads((run / "run_validation.toml").read_text(encoding="utf-8"))
    assert (
        v["full_simulation_passed"]
        and v["report_state_count"] == 516
        and abs(v["simulated_days"] - 2891) < 1e-6
    )
    assert not (run / "early_stop.json").exists()
    score = json.loads((run / "oil_water_score.json").read_text(encoding="utf-8"))
    rows.append(
        {
            "case": name,
            "complete_report_count": 516,
            "history_days": 2891,
            "combined_field_well_nrmse_pct": score["combined_field_well_nrmse_pct"],
            "field_oil_rmse_m3_day": score["field_full_period"]["oil_rmse_m3_day"],
            "field_water_rmse_m3_day": score["field_full_period"]["water_rmse_m3_day"],
            "well_oil_and_water_rates": score["full_period"]["per_well"],
        }
    )
ranking = sorted(rows, key=lambda row: row["combined_field_well_nrmse_pct"])
best = ranking[0]["case"]
assert best != "baseline_tuned", (
    "No complete candidate has improved the fixed primary score"
)
result = {
    "selection_criterion": (
        "Full-period oil/water NRMSE with prespecified equal weights for the field "
        "and well terms. Pressure, gas and extra terminal weighting are outside this "
        "ranking, which includes only completed cases."
    ),
    "selected_candidate": best,
    "full_period_candidate_ranking": ranking,
    "partial_run_notes": (
        "Only completed full-period simulations enter the ranking. Partial responses "
        "inform hypotheses for subsequent spatial edits."
    ),
    "interpretation_limits": (
        "The whole history informed the proposals. The case provides an in-sample "
        "match; the data do not establish a unique geological solution or general "
        "spatial reasoning ability."
    ),
}
path = ROOT / "results/full_period_candidate_ranking.json"
path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    json.dumps(
        {
            "selected_candidate": best,
            "full_ranking": [
                {k: v for k, v in row.items() if k != "well_oil_and_water_rates"}
                for row in ranking
            ],
        },
        ensure_ascii=False,
        indent=2,
    )
)
