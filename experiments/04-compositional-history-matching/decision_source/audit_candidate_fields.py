"""Audit cumulative edits relative to the explicit baseline using the actual files included by the DATA deck."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from compositional_tools import fields, array, NCOMP, SHAPE

parser = argparse.ArgumentParser()
parser.add_argument("name")
args = parser.parse_args()
assert Path(args.name).name == args.name and args.name not in {".", ".."}
source = ROOT / "candidates/baseline_explicit"
target = ROOT / "candidates" / args.name
old = fields(source)
new = fields(target)
indices = np.fromfile(ROOT / "runs/baseline_tuned/cell_map.bin", dtype=np.int64) - 1
active = np.zeros(np.prod(SHAPE), dtype=bool)
active[indices] = True
active = active.reshape(SHAPE)
allowed = {key + ".inc" for key in ["PORO", "PERMX", "PERMY", "PERMZ", "ZMF"]}
frozen = []
for path in source.iterdir():
    if not path.is_file() or path.name in allowed | {"patch.json", "field_patch.npz"}:
        continue
    other = target / path.name
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert other.is_file() and hashlib.sha256(other.read_bytes()).hexdigest() == sha, (
        path.name
    )
    frozen.append({"file": path.name, "SHA256": sha})
record = {
    "candidate": args.name,
    "reference_case": "baseline_explicit (original rock properties and original normalized composition)",
    "active_grid_cell_count": len(indices),
    "cumulative_changed_fields": {},
    "fixed_files": frozen,
}
for key in ["PORO", "PERMX", "PERMY", "PERMZ"]:
    a, b = old[key], new[key]
    assert np.isfinite(b).all() and np.array_equal(a[~active], b[~active])
    v = b[active]
    ratio = v / a[active]
    assert v.min() > 0
    if key == "PORO":
        assert v.max() < 1
    changed = np.abs(b - a) > 1e-14
    if changed[active].any():
        record["cumulative_changed_fields"][key] = {
            "changed_active_cells": int(changed[active].sum()),
            "min_value_active_field": float(v.min()),
            "max_value_active_field": float(v.max()),
            "min_cumulative_multiplier": float(ratio.min()),
            "max_cumulative_multiplier": float(ratio.max()),
        }
za = array(source / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
zb = array(target / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
assert np.isfinite(zb).all() and zb.min() >= 0
assert np.max(abs(zb.sum(axis=0) - 1)) < 1e-12
assert np.allclose(za[:, ~active], zb[:, ~active], atol=1e-15, rtol=0)
changed_z = np.any(abs(zb - za) > 1e-14, axis=0)
if changed_z[active].any():
    record["cumulative_changed_fields"]["ZMF"] = {
        "changed_active_cells": int(changed_z[active].sum()),
        "maximum_absolute_change": float(np.max(abs(zb - za))),
    }
record["initial_composition_constraints"] = {
    "min_component_fraction": float(zb.min()),
    "max_cell_composition_sum_deviation": float(np.max(abs(zb.sum(axis=0) - 1))),
    "changed_vs_normalized_initial_composition": bool(changed_z[active].any()),
}
run = ROOT / "runs" / args.name
native_base = ROOT / "runs/baseline_tuned"
native_indices = np.fromfile(run / "cell_map.bin", dtype=np.int64) - 1
assert np.array_equal(native_indices, indices)
native_phi = np.fromfile(run / "porosity.bin")
phi_error = float(np.max(abs(native_phi - new["PORO"].ravel()[indices])))
assert phi_error < 1e-14
# Compare multipliers on the same native grid to avoid assuming a separate mD-to-SI conversion factor.
native_k = np.fromfile(run / "permeability.bin").reshape((3, -1), order="F")
base_k = np.fromfile(native_base / "permeability.bin").reshape((3, -1), order="F")
native_errors = {"poro_max_absolute_difference": phi_error}
for row, key in enumerate(["PERMX", "PERMY", "PERMZ"]):
    ratio = new[key].ravel()[indices] / old[key].ravel()[indices]
    error = float(np.max(abs((native_k[row] / base_k[row]) / ratio - 1)))
    assert error < 1e-12, key
    native_errors[key.lower() + "_multiplier_max_relative_difference"] = error
native_z = np.fromfile(run / "initial_OverallMoleFractions.bin").reshape(
    (NCOMP, -1), order="F"
)
z_error = float(np.max(abs(native_z - zb.reshape((NCOMP, -1))[:, indices])))
assert z_error < 1e-12
native_errors["initial_zmf_max_absolute_difference"] = z_error
for key, tolerance, metric in [
    ("Pressure", 1e-5, "initial_pressure_max_abs_diff_vs_baseline"),
    (
        "ImmiscibleSaturation",
        1e-12,
        "initial_immiscible_saturation_max_abs_diff_vs_baseline",
    ),
]:
    value = np.fromfile(run / ("initial_" + key + ".bin"))
    reference = np.fromfile(native_base / ("initial_" + key + ".bin"))
    error = float(np.max(abs(value - reference)))
    assert error < tolerance
    native_errors[metric] = error
record["native_simulator_array_comparison"] = native_errors
record["matches_simulated_input_fields"] = True
record["all_constraints_passed"] = True
output = ROOT / "results" / (args.name + "_field_audit.json")
output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
print(
    json.dumps(
        {k: v for k, v in record.items() if k != "fixed_files"},
        ensure_ascii=False,
        indent=2,
    )
)
