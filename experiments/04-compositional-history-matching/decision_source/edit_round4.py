"""Round 4: use oil, water and Sw feedback at day 1,439 to distinguish early bottom-water influx from later injector connectivity."""

from datetime import datetime
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(1, str(ROOT.parent))
from compositional_tools import fields
from spatial_tools import native_fields, well_region, path_region
from field_edit import save_candidate

reference = fields(ROOT / "candidates/round1_k_only")
indices, xyz, connections = native_fields()
sw0 = np.fromfile(ROOT / "runs/baseline_tuned/initial_ImmiscibleSaturation.bin")
volume = np.fromfile(ROOT / "runs/baseline_tuned/volumes.bin")
bottom = np.load(ROOT / "topology/bottom_completion_paths.npz")
paths = np.load(ROOT / "topology/paths.npz")
safe = (sw0 < 0.99) & (reference["PORO"].ravel()[indices] * volume > 1e-3)
log_h = np.zeros(len(indices))
log_z = log_h.copy()
log_phi = log_h.copy()
controls = {
    "P11": {"kh": 1.0, "kz": 8.0, "phi": 0.65, "radius": 180.0, "vertical": 15.0},
    "P12": {"kh": 2.5, "kz": 2.0, "phi": 0.35, "radius": 180.0, "vertical": 20.0},
    "P13": {"kh": 1.0, "kz": 2.0, "phi": 0.85, "radius": 220.0, "vertical": 30.0},
    "P14": {"kh": 6.0, "kz": 2.0, "phi": 0.50, "radius": 220.0, "vertical": 30.0},
    "P15": {"kh": 2.7, "kz": 1.75, "phi": 0.72, "radius": 220.0, "vertical": 30.0},
    "P16": {"kh": 1.0, "kz": 1.0, "phi": 1.0, "radius": 220.0, "vertical": 30.0},
}
for well, control in controls.items():
    path_weight = path_region(
        xyz,
        bottom[well],
        horizontal_radius_m=control["radius"],
        vertical_radius_m=control["vertical"],
    )
    log_z += np.log(control["kz"]) * path_weight
    log_phi += np.log(control["phi"]) * path_weight * safe
    if well in {"P14", "P15", "P16"}:
        deepest = connections.loc[connections.well == well, "z"].max()
        near = well_region(xyz, connections, well, radius_m=220, vertical_padding_m=45)
        lower = 0.5 * (1 + np.tanh((xyz[2] - (deepest - 60.0)) / 20.0))
        weight = np.maximum(path_weight, near * lower)
    else:
        weight = path_weight
    log_h += np.log(control["kh"]) * weight

# P16 produced too much bottom water early and its subsequent growth was too slow. Test another connection under the fixed injection schedule.
flood = {
    "connection": "I12-W__P16",
    "kh": 5.0,
    "kz": 4.0,
    "phi": 0.80,
    "radius": 180.0,
    "vertical": 20.0,
}
weight = path_region(
    xyz,
    paths[flood["connection"]],
    horizontal_radius_m=flood["radius"],
    vertical_radius_m=flood["vertical"],
)
log_h += np.log(flood["kh"]) * weight
log_z += np.log(flood["kz"]) * weight
log_phi += np.log(flood["phi"]) * weight * safe
changed = {}
for key, factor in [
    ("PERMX", np.exp(log_h)),
    ("PERMY", np.exp(log_h)),
    ("PERMZ", np.exp(log_z)),
    ("PORO", np.exp(log_phi)),
]:
    value = reference[key].copy()
    value.ravel()[indices] *= factor
    changed[key] = value
rationale = {
    "decision_time": datetime.now().isoformat(),
    "objective": (
        "Full-period field and well oil and water production. Pressure and gas are "
        "outside the selection metric; terminal observations have no additional "
        "weight."
    ),
    "feedback_window": (
        "results/round3_oil_water_comparison_day1439.json and actual native responses "
        "and Sw from diagnostics_round3_1439 and diagnostics_round2_final_partial. "
        "Full-period candidate scores were pending."
    ),
    "available_observations": "All 2891 days of history were available. The experiment used no strict blind or holdout evaluation.",
    "P14": (
        "On day 1439 round three gave 298.32 m3/day of water against 601.79 observed. "
        "Water has arrived along the initial bottom-water path, but its contribution "
        "is too small. Raise the additional central multiplier on lower-zone Kh from "
        "3 to 6 and retain the previous Kz and porosity settings."
    ),
    "P15": (
        "Round three reduced water-rate RMSE from 125.80 to 21.29 m3/day. At day 1439 "
        "the rate was still 297.87 versus 225.996 observed. Reduce Kh slightly from 3 "
        "to 2.7 and retain Kz, porosity and the selected region."
    ),
    "p16_timing": (
        "On day 1281 round three gave 27.53 m3/day of water against 4.97 observed, "
        "but on day 1439 it gave 51.88 against 158.39. The direction of the error "
        "changes with time. Undo round three's additional bottom-water Kh and "
        "porosity edits, restore the round1_k_only reference and test the injector "
        "connection separately."
    ),
    "p16_injection_hypothesis": (
        "Historical I12-W injection starts on day 1210. During open intervals, "
        "injection-rate P10/P50/P90 is approximately 8387/9972/10192 m3/day. In round "
        "two on day 1440, Sw along the static path was about 0.396 at the source and "
        "0.317 in the next cell; the remaining cells toward P16 were still near 0.18. "
        "Test inadequate propagation along the injection connection. It is a "
        "candidate path, not a confirmed streamline."
    ),
    "p16_additional_path": flood,
    "p16_path_orientation": (
        "The 11-cell path has positive transmissibility, with lateral connections and "
        "five vertical connections. Adjust both Kh and Kz using horizontal and "
        "vertical length scales of 180 m and 20 m, with truncation at three scales."
    ),
    "P11": (
        "On day 1439 the water rate was 0.403 m3/day against 10.713 observed. "
        "Increase Kz near the lowest completion along the bottom-water path and "
        "reduce hydrocarbon-bearing pore volume. Narrow the vertical influence scale "
        "to 15 m to test slightly earlier water arrival while limiting invasion of "
        "higher layers."
    ),
    "P12": (
        "On day 1439 the water rate was 0.802 m3/day against 21.251 observed. Retain "
        "the central Kh and Kz multipliers, reduce the pathway porosity multiplier "
        "from 0.70 to 0.35 and narrow its spatial extent. Test front arrival time "
        "while limiting further increases in inflow capacity at the lowest "
        "completion."
    ),
    "P13": (
        "The current water rate is already close to history. Retain the round-three "
        "settings and check the late response over the full period."
    ),
    "bottom_water_central_multipliers_and_scales": controls,
    "multiplier_basis": (
        "Kh and Kz are relative to round1_k_only; porosity is relative to the "
        "original field. The I12-W to P16 pathway edit is applied smoothly on top of "
        "these fields. Evaluate the resulting arrays and any overlap of influence "
        "regions with the native simulator."
    ),
    "near_well_region": (
        "For P14/P15 use the lower 60 m with a smooth 20 m transition and a 220 m "
        "horizontal scale. Take the maximum of the near-well weight and each "
        "bottom-water path weight to avoid multiplying twice. The well region follows "
        "the connected completion-cell centers in the model; no separate directional "
        "survey is used."
    ),
    "porosity_constraints": (
        "Edit only active cells with initial Sw < 0.99 and cell pore volume > 1e-3 "
        "m3. Retain porosity in pure-water regions and keep active-cell porosities "
        "strictly between zero and one."
    ),
    "fixed_items": (
        "Retain the original normalized initial composition, nonnegative and summing "
        "to one cell by cell. Retain EOS, SCAL, well controls and completions, "
        "initial pressure/Sw, temperature, grid, numerical settings and simulator "
        "source."
    ),
    "pore_volume_original_m3": float(
        np.sum(reference["PORO"].ravel()[indices] * volume)
    ),
    "pore_volume_edited_m3": float(np.sum(changed["PORO"].ravel()[indices] * volume)),
    "full_verification_requirements": (
        "Recompute all 516 reports and 2891 days from t0. Partial responses, "
        "composition constraints and adherence to the liquid-rate control do not "
        "establish a complete history match."
    ),
}
print(save_candidate("round4_connectivity", changed, rationale, parent="round3_timing"))
(ROOT / "round4_decision.json").write_text(
    json.dumps(rationale, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(rationale, ensure_ascii=False, indent=2))
