"""Round 3: use the simulated round 2 oil and water responses to address premature water influx at P15 and P16."""

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
paths = np.load(ROOT / "topology/bottom_completion_paths.npz")
safe = (sw0 < 0.99) & (reference["PORO"].ravel()[indices] * volume > 1e-3)
log_h = np.zeros(len(indices))
log_z = log_h.copy()
log_phi = log_h.copy()
controls = {
    "P11": {"kh": 1.0, "kz": 3.0, "phi": 0.75},
    "P12": {"kh": 2.5, "kz": 2.0, "phi": 0.70},
    "P13": {"kh": 1.0, "kz": 2.0, "phi": 0.85},
    "P14": {"kh": 3.0, "kz": 2.0, "phi": 0.50},
    "P15": {"kh": 3.0, "kz": 1.75, "phi": 0.72},
    "P16": {"kh": 4.0, "kz": 1.0, "phi": 0.95},
}
for well, control in controls.items():
    path_weight = path_region(
        xyz, paths[well], horizontal_radius_m=220, vertical_radius_m=30
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
        "Full-period field and well oil and water rates. Pressure and gas are "
        "diagnostic and the final period has no extra weight."
    ),
    "feedback": (
        "results/round2_oil_water_comparison_day1281.json and the actual response "
        "from diagnostics_round2_1281. Coverage ends at day 1281; this is a "
        "window-specific comparison."
    ),
    "p14_retention_rationale": (
        "Over the same partial window, water-rate RMSE fell from 218.39 m3/day at "
        "baseline and 170.77 in round one to 62.77 in round two. Retain the round-two "
        "settings for P14 and check the full history for excessive late-time water."
    ),
    "p15_revision_rationale": (
        "On day 1281 the observed water rate was 86.35 m3/day and round two gave "
        "365.13 m3/day, indicating early water arrival. Reduce the multiplier on "
        "lower-zone Kh from 5 to 3 and the additional Kz multiplier from 3 to 1.75. "
        "Restore pathway porosity from 0.55 to 0.72 times the original value to delay "
        "the front and reduce early water supply."
    ),
    "p16_revision_rationale": (
        "On day 1281 the observed water rate was 4.97 m3/day and round two gave 51.11 "
        "m3/day. Sw was 0.336 at the deepest completion and 0.244 in the adjacent "
        "upper layer. Kz remained very low in several layers, indicating mainly "
        "along-layer water entry. Retain Kz, reduce the Kh enhancement from 8 to 4 "
        "and restore porosity from 0.65 to 0.95 times the original value to test "
        "front timing along the layer."
    ),
    "other_wells": (
        "Retain the round-two settings for P11, P12 and P13. Errors change little "
        "during the current low-water-cut period. Later low water production requires "
        "full-history evaluation."
    ),
    "central_multipliers": controls,
    "multiplier_reference": (
        "Kh and Kz are relative to round1_k_only, and porosity to the original "
        "porosity. Compared with round two, only the P15 and P16 influence regions "
        "change. The length scales and path definitions are identical."
    ),
    "region": (
        "As in round two, use Gaussian bottom-water path scales of 220 m horizontally "
        "and 30 m vertically; use the lower 60 m near the well with a smooth 20 m "
        "transition. Combine regions by maximum weight to avoid repeated "
        "multiplication."
    ),
    "path_scope": (
        "Use a static 1/T query on positive-transmissibility discrete connections. "
        "Check it against time-varying Sw and production curves; it does not "
        "establish an observed dynamic streamline."
    ),
    "porosity_constraints": (
        "Active cells that initially contain hydrocarbons and have pore volume > 1e-3 "
        "m3. Preserve pore volume in pure-water regions and retain the cell mapping."
    ),
    "initial_composition": "Retain the original normalized composition. Fractions are nonnegative and sum to one in every cell.",
    "fixed_conditions": (
        "Retain EOS, SCAL, well controls and completions, initial pressure and Sw, "
        "temperature, grid and simulator source."
    ),
    "pore_volume_original_m3": float(
        np.sum(reference["PORO"].ravel()[indices] * volume)
    ),
    "pore_volume_edited_m3": float(np.sum(changed["PORO"].ravel()[indices] * volume)),
    "full_verification": (
        "Rerun 516 report intervals over 2891 days from t0. Make the final selection "
        "using full-period oil and water metrics; partial windows support diagnosis."
    ),
}
print(save_candidate("round3_timing", changed, rationale, parent="round2_oil_water"))
(ROOT / "round3_decision.json").write_text(
    json.dumps(rationale, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(rationale, ensure_ascii=False, indent=2))
