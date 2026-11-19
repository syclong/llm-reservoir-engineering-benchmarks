"""Validate the 28 design variables and render a standalone DATA deck."""
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "inputs" / "BASE.DATA"
RULES = ROOT / "protocol.json"
WELLS = ("INJ1", "INJ2", "PROD1", "PROD2")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def write(path, text):
    """Write a temporary file in the same directory and replace the destination atomically."""
    path = Path(path)
    path.parent.mkdir(exist_ok=True, parents=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        tmp.write(text.encode("utf-8"))
        tmp_name = tmp.name
    os.replace(tmp_name, path)


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def parse_plan(raw):
    def reject_duplicates(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("Duplicate JSON key")
            result[k] = v
        return result
    x = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(x, dict) or set(x) != set(WELLS):
        raise ValueError("The proposal must contain exactly the four specified well names")
    for w in WELLS:
        a = x[w]
        if not isinstance(a, list) or len(a) != 7:
            raise ValueError("Each well needs two grid coordinates and five BHP targets")
        i, j, *bhp = a
        if type(i) is not int or type(j) is not int or not (1 <= i <= 60 and 1 <= j <= 50):
            raise ValueError("Well coordinates must be integers within the grid bounds")
        low, high = (275, 450) if w.startswith("INJ") else (100, 250)
        if any(type(v) not in (float, int) or not (low <= v <= high) for v in bhp):
            raise ValueError("BHP targets must be finite numbers within the permitted range")
    for w, other in itertools.combinations(WELLS, 2):
        if 32 * math.dist(x[w][:2], x[other][:2]) < 250:
            raise ValueError("The distance between any pair of well centers must be at least 250 m")
    return {w: x[w] for w in WELLS}


def canonical(plan):
    """Sort wells of the same type with their full pressure schedules to identify physically equivalent plans."""
    return tuple(tuple(v) for group in (WELLS[:2], WELLS[2:]) for v in sorted(plan[w] for w in group))


def render(plan):
    """Replace well locations, completion coordinates, and five BHP targets per well in the common template."""
    parse_plan(dump(plan))
    text = BASE.read_text(encoding="utf-8")
    prefix, sched = text.split("\nSCHEDULE\n", 1)
    active_kw = ""
    change_period = {w: 0 for w in WELLS}
    out = []
    for line in sched.splitlines():
        token = line.strip()
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", token):
            active_kw = token
        match = re.match(r"\s*'(INJ1|INJ2|PROD1|PROD2)'", line)
        if match:
            w = match[1]
            i, j, *pressures = plan[w]
            if active_kw in ("WELSPECS", "COMPDAT"):
                pattern = (r"^(\s*'\w+'\s+'GROUP1'\s+)\d+\s+\d+"
                           if active_kw == "WELSPECS" else r"^(\s*'\w+'\s+)\d+\s+\d+")
                line, n = re.subn(pattern, lambda m: m[1] + f"{i} {j}", line)
                if n != 1:
                    raise ValueError("The well location record does not match the deck template")
            elif active_kw in ("WCONINJE", "WCONPROD", "WELTARG"):
                if active_kw == "WELTARG":
                    change_period[w] += 1
                p = pressures[change_period[w]]
                line, n = re.subn(r"[-+\d.]+\s*/\s*$", lambda _: str(p)+" /", line)
                if n != 1:
                    raise ValueError("The BHP record does not match the deck template")
        out.append(line)
    if set(change_period.values()) != {4}:
        raise ValueError("Each well must have five control periods")
    return prefix + "\nSCHEDULE\n" + "\n".join(out) + "\n"
