"""Round 2: update rock properties along lower water-supply connections."""

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

parent = "round1_k_only"
base = fields(ROOT / "candidates" / parent)
indices, xyz, connections = native_fields()
sw0 = np.fromfile(ROOT / "runs/baseline_tuned/initial_ImmiscibleSaturation.bin")
volume = np.fromfile(ROOT / "runs/baseline_tuned/volumes.bin")
paths = np.load(ROOT / "topology/bottom_completion_paths.npz")
oil = sw0 < 0.99
safe = base["PORO"].ravel()[indices] * volume > 1e-3
log_h = np.zeros(len(indices))
log_z = np.zeros(len(indices))
log_phi = np.zeros(len(indices))

# Full-period observations were available. Forward-run feedback covered only the first 1,488 days and could not establish full-period performance.
controls = {
    "P11": {"kh": 1.0, "kz": 3.0, "phi": 0.75},
    "P12": {"kh": 2.5, "kz": 2.0, "phi": 0.70},
    "P13": {"kh": 1.0, "kz": 2.0, "phi": 0.85},
    "P14": {"kh": 3.0, "kz": 2.0, "phi": 0.50},
    "P15": {"kh": 5.0, "kz": 3.0, "phi": 0.55},
    "P16": {"kh": 8.0, "kz": 1.0, "phi": 0.65},
}
for well, control in controls.items():
    path_weight = path_region(
        xyz, paths[well], horizontal_radius_m=220, vertical_radius_m=30
    )
    log_z += np.log(control["kz"]) * path_weight
    log_phi += np.log(control["phi"]) * path_weight * oil * safe
    if well in {"P14", "P15", "P16"}:
        deepest = connections.loc[connections.well == well, "z"].max()
        near = well_region(xyz, connections, well, radius_m=220, vertical_padding_m=45)
        lower = 0.5 * (1 + np.tanh((xyz[2] - (deepest - 60.0)) / 20.0))
        # Cover the lower part of the deepest completion and the bottom-water connection. Apply the larger weight where the regions overlap.
        horizontal_weight = np.maximum(path_weight, near * lower)
    else:
        horizontal_weight = path_weight
    log_h += np.log(control["kh"]) * horizontal_weight

changed = {}
for key, factor in [
    ("PERMX", np.exp(log_h)),
    ("PERMY", np.exp(log_h)),
    ("PERMZ", np.exp(log_z)),
    ("PORO", np.exp(log_phi)),
]:
    value = base[key].copy()
    value.ravel()[indices] *= factor
    changed[key] = value

rationale = {
    "decision_time": datetime.now().isoformat(),
    "objective": (
        "Full-period field FOPR/FWPR and well WOPR/WWPR. Pressure and gas production "
        "are diagnostic; the end of history receives the same weighting as other "
        "periods."
    ),
    "feedback_evidence": (
        "round1_oil_water_partial_comparison.json: actual simulated responses through "
        "the common day 1488 and the near-well Sw field at the same time."
    ),
    "known_history_window": "All 2891 days of observations were available. The experiment used no strict blind or holdout evaluation.",
    "parent_version": parent,
    "inherited_permeability": (
        "Start from the round-one permeability-only input. The near-well horizontal "
        "permeability reduction was originally suggested by pressure diagnostics. "
        "Judge its retention using oil and water only; the pressure improvement is "
        "outside the score."
    ),
    "additional_central_multipliers": controls,
    "porosity_multiplier_basis": "Relative to the original porosity. The porosity in the parent round1_k_only is the same as the baseline.",
    "permeability_multiplier_basis": (
        "Relative to parent round1_k_only and applied on top of its existing edits. "
        "These are additional multipliers, rather than totals relative to the "
        "original field."
    ),
    "p14_rationale": (
        "On day 1488 the water rate was 199.82 m3/day against 862.36 observed. Water "
        "was already present in eight lower completion cells. Test the fraction of "
        "lower-zone inflow and vertical water propagation. First water arrival "
        "preceded injection."
    ),
    "p15_rationale": (
        "On day 1488 the water rate was 45.96 m3/day against 318.78 observed. Sw rose "
        "mainly in three lower completion cells. Increase lower-zone horizontal "
        "inflow capacity and vertical connectivity and reduce hydrocarbon-bearing "
        "pore volume along the path."
    ),
    "p16_rationale": (
        "On day 1488 the water rate was 18.91 m3/day against 252.49 observed. Sw at "
        "the deepest completion was approximately 0.326. The previous "
        "minimum-resistance path to any completion missed the deepest water-entry "
        "layer. The discrete path to the deepest completion has four cells, all in "
        "layer K219. Increase permeability along that path and Kh in the lower zone."
    ),
    "low_water_cut_well_rationale": (
        "Near day 1488 the observed P11/P12 water rates were 14.20/26.10 m3/day and "
        "the simulations gave 0.53/0.31. Modestly accelerate deep bottom-water "
        "arrival. P13 is close at this point but water rises later, so use a weaker "
        "edit and check for premature arrival over the complete history."
    ),
    "path_type": (
        "Use shortest static paths with cost 1/T on actual positive-transmissibility "
        "connections to locate candidate regions. Evaluate them using simulated Sw "
        "and timing since the static paths are not verified dynamic streamlines."
    ),
    "region": (
        "Use a 3D Gaussian around the bottom-water path to the deepest completion, "
        "with horizontal and vertical scales of 220 m and 30 m and zero weight beyond "
        "three scales. At wet wells, use a 20 m tanh transition over the lower 60 m "
        "and a 220 m horizontal Gaussian. Combine regions by maximum weight to avoid "
        "multiplying overlaps twice."
    ),
    "porosity_constraints": (
        "Edit only active cells with initial Sw < 0.99 and cell pore volume > 1e-3 "
        "m3. Retain pore volume in pure-water cells."
    ),
    "initial_composition": (
        "Retain the original normalized composition. This round makes no composition "
        "edit to fit the gas-oil ratio. Fractions still sum to one in every cell."
    ),
    "fixed_items": (
        "Retain the well controls, liquid rate, initial pressure and Sw, temperature, "
        "EOS, SCAL, grid and simulator source."
    ),
    "pore_volume_original_m3": float(np.sum(base["PORO"].ravel()[indices] * volume)),
    "pore_volume_edited_m3": float(np.sum(changed["PORO"].ravel()[indices] * volume)),
    "completion_criteria": (
        "Rerun all 516 intervals over 2891 days from t0. Compute the primary score "
        "after native input and report-state checks pass."
    ),
}
path = save_candidate("round2_oil_water", changed, rationale, parent=parent)
(ROOT / "round2_decision.json").write_text(
    json.dumps(rationale, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("Saved: ", path)
print(json.dumps(rationale, ensure_ascii=False, indent=2))
