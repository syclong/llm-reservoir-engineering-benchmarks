"""Round 1: apply near-well, bottom-water and composition edits."""

from datetime import datetime
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(1, str(ROOT.parent))
from compositional_tools import fields, array, SHAPE, NCOMP, transfer_components
from spatial_tools import native_fields, well_region, path_region
from field_edit import save_candidate

base = ROOT / "candidates/baseline_explicit"
original = fields(base)
indices, xyz, connections = native_fields()
sw = np.fromfile(ROOT / "runs/baseline_tuned/initial_ImmiscibleSaturation.bin")
volumes = np.fromfile(ROOT / "runs/baseline_tuned/volumes.bin")
porosity = original["PORO"].ravel()[indices]
oil = sw < 0.99
safe_pore_volume = porosity * volumes > 1e-3
log_kh = np.zeros(len(indices))
log_kz = np.zeros(len(indices))
log_phi = np.zeros(len(indices))

# Simulated BHP was generally too high through day 1,488. The Darcy relationship between the original background pressure and drawdown informed the diagnosis.
near_well_factors = {
    "P11": 0.35,
    "P12": 0.50,
    "P13": 0.40,
    "P14": 0.40,
    "P15": 0.32,
    "P16": 0.35,
}
for well, factor in near_well_factors.items():
    weight = well_region(xyz, connections, well, radius_m=300, vertical_padding_m=45)
    log_kh += np.log(factor) * weight
    if well in {"P11", "P12", "P13"}:
        log_kz += np.log(factor) * weight

# P14 first produced water before injection began at any well. Test bottom-water coning at P14 and lower water-influx paths at P15 and P16.
# Reduce only the originally hydrocarbon-bearing pore volume along the paths. Preserve storage in cells initially filled with water.
paths = np.load(ROOT / "topology/paths.npz")
bottom_controls = {
    "P14": {"kz": 6.0, "poro": 0.70},
    "P15": {"kz": 2.5, "poro": 0.80},
    "P16": {"kz": 1.5, "poro": 0.90},
}
for well, control in bottom_controls.items():
    weight = path_region(
        xyz,
        paths["initial_bottom_water__" + well],
        horizontal_radius_m=250,
        vertical_radius_m=25,
    )
    log_kz += np.log(control["kz"]) * weight
    log_phi += np.log(control["poro"]) * weight * oil * safe_pore_volume

changed = {}
for key, factor in [
    ("PERMX", np.exp(log_kh)),
    ("PERMY", np.exp(log_kh)),
    ("PERMZ", np.exp(log_kz)),
    ("PORO", np.exp(log_phi)),
]:
    value = original[key].copy()
    value.ravel()[indices] *= factor
    changed[key] = value

# In the first 90 days the six wells had gas/oil ratios of about 428–434 versus about 406 with the original composition. Test a shared initial composition bias.
# Transfer 0.007 mole fraction from C6C19 to N2C1, adding and subtracting the same fraction in each cell to preserve a unit sum.
z = array(base / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
amount = np.zeros(np.prod(SHAPE))
amount[indices[oil]] = 0.007
changed["ZMF"] = transfer_components(z, 3, 1, amount.reshape(SHAPE))

rationale = {
    "decision_time": datetime.now().isoformat(),
    "feedback_window": (
        "diagnostics_baseline_mid: six-well forward responses for the first 1488 days "
        "of the original field. The formal baseline continues over all 2891 days."
    ),
    "available_observations": "The entire original history was available. The evaluation did not use a strict blind or held-out test.",
    "near_well_horizontal_permeability_central_multiplier": near_well_factors,
    "near_well_region": (
        "Use a 3D Gaussian region along the original completions, with a 300 m "
        "horizontal radius and a 45 m vertical scale. Retain the original values "
        "beyond three scales."
    ),
    "near_well_rationale": (
        "Simulated BHP is too high. Reduce near-well horizontal inflow capacity to "
        "produce greater drawdown at the same liquid rate. At low-water-cut "
        "P11/P12/P13, also reduce Kz to maintain the local permeability anisotropy."
    ),
    "bottom_water_path": bottom_controls,
    "bottom_water_rationale": (
        "Historical P14 water cut exceeded 1% on day 1101, before the earliest "
        "injection on day 1167.4. Test upward migration of initial bottom water. The "
        "region follows a static low-resistance path through actual discrete "
        "connections; dynamic flow along that path remains a hypothesis."
    ),
    "bottom_water_region": (
        "Use a smooth region around the actual bottom-water path with a 250 m "
        "horizontal scale and 25 m vertical scale. Edit porosity only in active cells "
        "initially containing hydrocarbons with pore volume > 1e-3 m3."
    ),
    "initial_composition": (
        "In active cells initially containing hydrocarbons, increase N2C1 by 0.007 "
        "and decrease C6C19 by 0.007, keeping the other components fixed. This tests "
        "the common underprediction of the gas-oil ratio."
    ),
    "pore_volume_original_m3": float(np.sum(porosity * volumes)),
    "pore_volume_edited_m3": float(np.sum(changed["PORO"].ravel()[indices] * volumes)),
    "full_period_comparison_criteria": (
        "Use the same native simulator and TUNING for every candidate. Compare after "
        "all 2891 days; satisfying the liquid-rate constraint does not independently "
        "demonstrate a match."
    ),
}

for name, keys, description in [
    (
        "round1_full",
        ["PERMX", "PERMY", "PERMZ", "PORO", "ZMF"],
        "Full round-one field edit",
    ),
    (
        "round1_k_only",
        ["PERMX", "PERMY", "PERMZ"],
        "Retain exactly the same permeability edits and use baseline porosity and composition.",
    ),
    (
        "round1_k_phi",
        ["PERMX", "PERMY", "PERMZ", "PORO"],
        "Retain the same porosity and permeability edits and the baseline composition.",
    ),
]:
    path = save_candidate(
        name,
        {key: changed[key] for key in keys},
        {**rationale, "comparison_definition": description},
    )
    print("Saved: ", path)
(ROOT / "round1_decision.json").write_text(
    json.dumps(rationale, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(rationale, ensure_ascii=False, indent=2))
