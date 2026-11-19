"""Fixed item-level scoring, with a separate denominator for each scientific question."""
import json
from collections import Counter
from math import isfinite


def parse_answer(raw):
    def unique(items):
        d = dict(items)
        if len(d) != len(items):
            raise ValueError("Duplicate JSON object key")
        return d
    def bad_constant(token):
        raise ValueError(f"Invalid JSON constant {token}")
    data = json.loads(raw, object_pairs_hook=unique, parse_constant=bad_constant)
    if not isinstance(data, dict):
        raise ValueError("The response must be a JSON object")
    return data


def same(value, target, tol=0):
    if isinstance(target, bool):
        return value is target
    if isinstance(target, (float, int)):
        return type(value) in (int, float) and isfinite(value) and abs(value - target) <= tol
    if isinstance(target, list):
        return isinstance(value, list) and len(value) == len(target) and all(same(v, t) for v, t in zip(value, target))
    return isinstance(value, type(target)) and value == target


def keyed(items, key, expected):
    def canonical(v):
        if isinstance(v, list):
            if key == "wells" and all(isinstance(s, str) for s in v):
                return sorted(v)
            return v
        return v
    if not isinstance(items, list):
        return {}
    found = [row for row in items if isinstance(row, dict) and same(canonical(row.get(key)), canonical(expected))]
    return found[0] if len(found) == 1 else {}


def evaluate(ref, answer):
    rows = []
    def check(group, item, got, expected, tol=0, accepted=None):
        options = accepted if accepted is not None else [expected]
        hit = any(same(got, option, tol) for option in options)
        rows.append(dict(group=group, item=item, actual=got, expected=expected, correct=hit))
    def obj(key):
        v = answer.get(key)
        return v if isinstance(v, dict) else {}

    geo, fluids = obj("geology"), obj("fluids")
    for k in ("dims", "active_by_k", "dx_m", "dy_m"):
        check("grid_and_structure", k, obj("grid").get(k), ref["grid"][k], .5 if k.endswith("_m") else 0)
    for k in ("structure", "crest_ij", "crest_top_m"):
        options = ref["geology"]["tied_crest_ij"] if k == "crest_ij" else None
        check("grid_and_structure", k, geo.get(k), ref["geology"][k], .5 if k.endswith("_m") else 0, options)
    for k, target in ref["fluids"].items():
        got = fluids.get(k)
        if k == "phases":
            if isinstance(got, list) and all(isinstance(s, str) for s in got):
                got = sorted(s.lower() for s in got)
            target = sorted(target)
        check("fluids", k, got, target, .1 if k.endswith("_bar") else .5 if k.endswith("_m") else 0)
    for layer in ref["layers"]:
        k = layer["k"]
        data = keyed(answer.get("layers"), "k", k)
        for field in ("role", "high_perm_cells", "high_perm_bodies", "mean_thickness_m"):
            check("layers", f"K{k}.{field}", data.get(field), layer[field], .5 if field.endswith("_m") else 0)
    for edge in ref["vertical"]:
        data = keyed(answer.get("vertical"), "k", edge["k"])
        check("vertical_interfaces", str(edge["k"]), data.get("formation_link"), edge["formation_link"])
    for well in ref["wells"]:
        w = well["name"]
        data = keyed(answer.get("wells"), "name", w)
        for field in ("ij", "open_k", "control", "oil_target_sm3_d", "bhp_limit_bar"):
            got = data.get(field)
            if field == "open_k" and isinstance(got, list) and all(type(v) is int for v in got):
                got = sorted(got)
            group = "well_locations_and_completions" if field in ("ij", "open_k") else "controls_and_schedule"
            check(group, f"{w}.{field}", got, well[field], .1 if field.endswith(("_bar", "_d")) else 0)
    check("controls_and_schedule", "schedule_days", answer.get("schedule_days"), ref["schedule_days"], .01)
    pay = {layer["k"] for layer in ref["layers"] if layer["high_perm_cells"]}
    for pair in ref["pairs"]:
        w = pair["wells"]
        name = "/".join(w)
        data = keyed(answer.get("pairs"), "wells", w)
        by_k = data.get("same_body_by_k")
        for index, expected in enumerate(pair["same_body_by_k"]):
            label = "reservoir_pair_layers" if index + 1 in pay else "nonreservoir_pair_layers"
            got = by_k[index] if isinstance(by_k, list) and len(by_k) == len(pair["same_body_by_k"]) else None
            check(label, f"{name}.K{index + 1}", got, expected)
        check("open_completion_pairs", name, data.get("open_completion_link"), pair["open_completion_link"])
    totals = Counter(row["group"] for row in rows)
    hits = Counter(row["group"] for row in rows if row["correct"])
    return {"groups": {g: {"correct": hits[g], "total": v} for g, v in totals.items()}, "items": rows}
