"""Validate and serialize property arrays and verify fixed inputs."""

import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from compositional_tools import (
    fields,
    array,
    normalize_composition,
    write_array,
    SHAPE,
    NCOMP,
)


def save_candidate(name, changes, rationale, parent="baseline_explicit"):
    source = ROOT / "candidates" / parent
    target = ROOT / "candidates" / name
    if target.exists():
        raise FileExistsError(target)
    if not changes or set(changes) - {"PORO", "PERMX", "PERMY", "PERMZ", "ZMF"}:
        raise ValueError(
            "Only porosity, permeability and initial composition may be edited"
        )
    validation = ROOT / "import_baseline_explicit/input_validation.toml"
    complete = ROOT / "runs/baseline_tuned/run_validation.toml"
    if not validation.is_file():
        raise ValueError(
            "Verify the explicit initial state against the original before editing"
        )
    if complete.is_file():
        assert tomllib.loads(complete.read_text(encoding="utf-8"))[
            "full_simulation_passed"
        ]
    else:
        diagnostics = ROOT / "diagnostics_baseline_mid/diagnostics.toml"
        if (
            not diagnostics.is_file()
            or tomllib.loads(diagnostics.read_text(encoding="utf-8"))["simulated_days"]
            < 1488
        ):
            raise ValueError(
                "The baseline simulation has not yet produced enough feedback"
            )
        status = ROOT / "control_numeric/04_full_baseline_tuned.toml.status.toml"
        if (
            status.is_file()
            and not tomllib.loads(status.read_text(encoding="utf-8"))["success"]
        ):
            raise ValueError(
                "The baseline simulation failed. Resolve the failure before continuing history matching."
            )
    assert tomllib.loads(validation.read_text(encoding="utf-8"))[
        "initial_pressure_and_water_saturation_match"
    ]
    if not (source / "ZMF.inc").is_file():
        raise ValueError("The parent must have a verified explicit ZMF input")
    old = fields(source)
    active_index = (
        np.fromfile(ROOT / "runs/pilot_baseline/cell_map.bin", dtype=np.int64) - 1
    )
    active = np.zeros(np.prod(SHAPE), dtype=bool)
    active[active_index] = True
    active = active.reshape(SHAPE)
    oldz = normalize_composition(
        array(ROOT / "candidates/baseline/COMPOSITION.inc", "ZMFVD").reshape((-1, 6))[
            0, 1:
        ]
    )
    defaultz = np.broadcast_to(oldz[:, None, None, None], (NCOMP, *SHAPE)).copy()
    if (source / "ZMF.inc").is_file():
        old["ZMF"] = array(source / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
    else:
        old["ZMF"] = defaultz
    checked = {}
    for key, value in changes.items():
        value = np.asarray(value, dtype=np.float64)
        if value.shape != old[key].shape or not np.isfinite(value).all():
            raise ValueError("Invalid field shape or nonfinite values in " + key)
        if key == "ZMF":
            value = normalize_composition(value)
            if not np.allclose(
                value[:, ~active], old[key][:, ~active], rtol=0, atol=1e-15
            ):
                raise ValueError("Composition changes are limited to active cells")
        else:
            if not np.array_equal(value[~active], old[key][~active]):
                raise ValueError("Property changes are limited to active cells")
            if key == "PORO" and (
                np.any(value[active] <= 0) or np.any(value[active] >= 1)
            ):
                raise ValueError(
                    "Active-cell porosity must be strictly between zero and one"
                )
            if key.startswith("PERM") and np.any(value[active] <= 0):
                raise ValueError("Active-cell permeability must be positive")
        checked[key] = value
    shutil.copytree(source, target)
    record = {
        "candidate": name,
        "parent_version": parent,
        "edit_rationale": rationale,
        "fields": {},
        "parallel_execution_note": (
            "Propose candidates using already simulated windows. The baseline and ranked "
            "candidates must each complete 2891 days under the same scoring rules."
        ),
    }
    editable = {key + ".inc" for key in checked}
    for key, value in checked.items():
        path = target / (key + ".inc")
        write_array(path, key, value)
        reread = array(path, key).reshape(value.shape)
        if not np.allclose(value, reread, rtol=5e-15, atol=1e-16):
            raise ValueError("Field serialization error exceeds tolerance")
        changed = (
            np.any(abs(reread - old[key]) > 1e-14, axis=0)
            if key == "ZMF"
            else abs(reread - old[key]) > 1e-14
        )
        r = {
            "changed_active_grid_cells": int(changed[active].sum()),
            "min": float(reread.min()),
            "max": float(reread.max()),
        }
        if key == "ZMF":
            deviation = float(np.max(abs(reread.sum(axis=0) - 1)))
            if np.any(reread < 0) or deviation > 1e-12:
                raise ValueError("The serialized composition violates its constraints")
            r["max_grid_cell_composition_sum_deviation"] = deviation
        record["fields"][key] = r
    frozen = []
    for path in source.iterdir():
        if not path.is_file() or path.name in editable | {
            "patch.json",
            "field_patch.npz",
        }:
            continue
        expected = hashlib.sha256(path.read_bytes()).hexdigest()
        assert (
            hashlib.sha256((target / path.name).read_bytes()).hexdigest() == expected
        ), path.name
        frozen.append({"file": path.name, "sha256": expected})
    record["fixed_file_checks"] = frozen
    np.savez_compressed(target / "field_patch.npz", **checked)
    (target / "patch.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target
