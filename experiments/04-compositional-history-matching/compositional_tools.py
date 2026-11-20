"""Audit compositional case inputs, extract observations and apply constrained field edits."""

from __future__ import annotations
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
ORIGINAL = (
    ROOT / "original" if (ROOT / "original").is_dir() else ROOT / "reference_model"
)
SHAPE = (291, 39, 47)
NCELLS = int(np.prod(SHAPE))
NCOMP = 5
COMPONENTS = ["CO2", "N2C1", "C2NC5", "C6C19", "C29C63"]
START = datetime(2018, 9, 2)


def text(path):
    return Path(path).read_text(encoding="utf-8").replace("\r", "")


def array(path, keyword):
    source = re.sub(r"--[^\n]*", "", text(path))
    match = re.search(r"\b" + re.escape(keyword) + r"\b\s*([^/]+)/", source, re.I)
    if not match:
        raise ValueError(f"Cannot find {keyword} in {path}")
    data = match[1]
    if "*" not in data:
        return np.fromstring(data, sep=" ")
    values = []
    for token in data.split():
        if "*" in token:
            count, value = token.split("*", 1)
            if not value:
                raise ValueError("Array repeat has no explicit value: " + token)
            values.extend([float(value)] * int(count))
        else:
            values.append(float(token))
    return np.asarray(values)


def fields(base=ORIGINAL):
    data = {
        key: array(base / (key + ".inc"), key)
        for key in ["ACTNUM", "PORO", "PERMX", "PERMY", "PERMZ", "SATNUM"]
    }
    for key, value in data.items():
        if value.size != NCELLS:
            raise ValueError(f"Expected {NCELLS} values for {key}, found {value.size}")
        data[key] = value.reshape(SHAPE)
    return data


def normalize_composition(z):
    """Normalize along the first (component) axis. Reject negative values and zero totals without clipping."""
    z = np.asarray(z, dtype=np.float64)
    if z.shape[0] != NCOMP or not np.all(np.isfinite(z)) or np.any(z < 0):
        raise ValueError(
            "The composition has the wrong component count or contains nonfinite or negative values"
        )
    totals = z.sum(axis=0)
    if np.any(totals <= 0):
        raise ValueError("The sum of component fractions must be positive")
    result = z / totals
    result[-1] = 1 - result[:-1].sum(axis=0)
    if np.any(result < 0) or np.max(abs(result.sum(axis=0) - 1)) > 1e-12:
        raise ValueError("Could not normalize the composition")
    return result


def transfer_components(z, source_component, target_component, amount):
    """Apply the specified spatial transfer by subtracting from one component and adding the same amount to another."""
    result = np.array(z, dtype=np.float64, copy=True)
    if source_component == target_component:
        raise ValueError("Source and target components must differ")
    amount = np.asarray(amount)
    if np.any(amount < 0) or np.any(amount > result[source_component]):
        raise ValueError(
            "The transfer must be nonnegative and cannot exceed the source fraction"
        )
    result[source_component] -= amount
    result[target_component] += amount
    return normalize_composition(result)


def write_array(path, keyword, values):
    """Write values in component-major, K/J/I order, compressing consecutive equal values losslessly."""
    values = np.asarray(values, dtype=np.float64).ravel()
    if not np.all(np.isfinite(values)):
        raise ValueError("The output array contains nonfinite values")
    starts = np.r_[0, np.flatnonzero(values[1:] != values[:-1]) + 1]
    ends = np.r_[starts[1:], len(values)]
    tokens = []
    for start, end in zip(starts, ends):
        value = f"{values[start]:.16g}"
        count = end - start
        tokens.append(f"{count}*{value}" if count > 2 else " ".join([value] * count))
    output = (
        keyword
        + "\n"
        + "\n".join(" ".join(tokens[n : n + 6]) for n in range(0, len(tokens), 6))
        + "\n/\n"
    )
    Path(path).write_text(output, encoding="utf-8")


def expand_record(line):
    result = []
    for token in re.findall(r"'[^']*'|[^\s/]+", line):
        if "*" in token and not token.startswith("'"):
            count, value = token.split("*", 1)
            result.extend([value if value else None] * int(count))
        else:
            result.append(token.strip("'"))
    return result


def history(history_file=None):
    source = re.sub(
        r"--[^\n]*",
        "",
        text(
            Path(history_file) if history_file is not None else ORIGINAL / "HISTORY.inc"
        ),
    )
    blocks = list(re.finditer(r"(?m)^\s*(WCONHIST|WCONINJH|TSTEP)\s*$", source))
    rows = []
    pending = []
    days = 0.0
    for n, match in enumerate(blocks):
        body = source[
            match.end() : blocks[n + 1].start() if n + 1 < len(blocks) else len(source)
        ]
        kind = match[1]
        if kind == "TSTEP":
            for step in expand_record(body):
                dt = float(step)
                if dt <= 0:
                    raise ValueError("The time step must be positive")
                for row in pending:
                    rows.append(
                        {
                            **row,
                            "start_days": days,
                            "end_days": days + dt,
                            "date": START + timedelta(days=days + dt),
                        }
                    )
                days += dt
            pending = []
            continue
        for record in body.split("/"):
            items = expand_record(record)
            if not items:
                continue
            if kind == "WCONHIST":
                pending.append(
                    {
                        "well": items[0],
                        "kind": "producer",
                        "phase": "MULTI",
                        "status": items[1],
                        "control": items[2],
                        "qo_obs": float(items[3]),
                        "qw_obs": float(items[4]),
                        "qg_obs": float(items[5]),
                        "bhp_obs": float(items[9])
                        if len(items) > 9 and items[9] is not None
                        else np.nan,
                        "thp_obs": float(items[8])
                        if len(items) > 8 and items[8] is not None
                        else np.nan,
                    }
                )
            else:
                pending.append(
                    {
                        "well": items[0],
                        "kind": "injector",
                        "phase": items[1],
                        "status": items[2],
                        "control": "RATE",
                        "injection_obs": float(items[3]),
                        "bhp_obs": float(items[4])
                        if len(items) > 4 and items[4] is not None
                        else np.nan,
                        "thp_obs": float(items[5])
                        if len(items) > 5 and items[5] is not None
                        else np.nan,
                    }
                )
    return pd.DataFrame(rows)


def audit():
    data = fields()
    active = data["ACTNUM"] > 0
    report = {
        "grid_dimensions_ijk": [47, 39, 291],
        "total_grid_cells": NCELLS,
        "actnum_active_cells": int(active.sum()),
        "active_cells_with_zero_porosity": int((active & (data["PORO"] == 0)).sum()),
        "fields": {},
    }
    for key in ["PORO", "PERMX", "PERMY", "PERMZ"]:
        values = data[key][active]
        report["fields"][key] = {"min": float(values.min()), "max": float(values.max())}
    z = array(ORIGINAL / "PROPS_EOS.inc", "ZI")
    report["initial_composition"] = {
        "names": COMPONENTS,
        "original_values": z.tolist(),
        "original_sum": float(z.sum()),
        "normalized_values": normalize_composition(z).tolist(),
    }
    hist = history()
    hist.to_csv(ROOT / "history_observations.csv", index=False, encoding="utf-8")
    report["history"] = {
        "records": len(hist),
        "wells": hist.well.nunique(),
        "producers": hist[hist.kind == "producer"].well.nunique(),
        "injectors": hist[hist.kind == "injector"].well.nunique(),
        "intervals": hist.end_days.nunique(),
        "end_days": float(hist.end_days.max()),
        "end_date": str(hist.date.max()),
        "injector_records_with_observed_bhp": int(
            hist[(hist.kind == "injector") & hist.bhp_obs.notna()].shape[0]
        ),
        "injector_records_with_observed_thp": int(
            hist[(hist.kind == "injector") & hist.thp_obs.notna()].shape[0]
        ),
    }
    (ROOT / "case_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    audit()
