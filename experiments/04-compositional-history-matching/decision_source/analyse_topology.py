"""Query connectivity and relative-resistance paths on actual discrete connections."""

import json
from pathlib import Path
import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from spatial_tools import native_fields

ROOT = Path(__file__).resolve().parent
indices, xyz, wells = native_fields()
neighbors = (
    np.fromfile(ROOT / "topology/neighbors.bin", dtype=np.int64).reshape(
        (2, -1), order="F"
    )
    - 1
)
t = np.fromfile(ROOT / "topology/transmissibility.bin")
assert np.isfinite(t).all() and np.all(t >= 0)
positive = t > 0
reference = float(np.median(t[positive]))
n = len(indices)
rows, cols = neighbors[:, positive]
weights = reference / t[positive]
graph = coo_matrix(
    (np.r_[weights, weights], (np.r_[rows, cols], np.r_[cols, rows])), shape=(n, n)
).tocsr()
count, labels = connected_components(graph, directed=False)
report = {
    "active_cells": n,
    "discrete_connections": len(t),
    "zero_transmissibility_connections": int((~positive).sum()),
    "positive_transmissibility_component_count": count,
    "path_notes": (
        "A static minimum-resistance path uses reciprocal transmissibility as its "
        "cost. It is a spatial query that omits evolving pressure differences, "
        "relative permeability and wellbore mixing. It does not measure a tracer path "
        "or breakthrough time."
    ),
    "well_connection_components": {},
    "injector_to_producer_relative_resistance_paths": {},
}
for well, d in wells.groupby("well"):
    ids = d.active_index.to_numpy() - 1
    labs, counts = np.unique(labels[ids], return_counts=True)
    report["well_connection_components"][well] = {
        str(i): int(c) for i, c in zip(labs, counts)
    }
paths = {}
initial_water = np.fromfile(
    ROOT / "runs/baseline_tuned/initial_ImmiscibleSaturation.bin"
)
for injector in [
    "initial_bottom_water",
    "I11-W",
    "I12-W",
    "I13-W",
    "I14-W",
    "I15-W",
    "I17-W",
    "I16",
]:
    if injector == "initial_bottom_water":
        seeds = np.flatnonzero(initial_water > 0.99)
    else:
        seeds = wells[wells.well == injector].active_index.to_numpy() - 1
    distance, predecessors, sources = dijkstra(
        graph, directed=False, indices=seeds, min_only=True, return_predecessors=True
    )
    for producer in ["P11", "P12", "P13", "P14", "P15", "P16"]:
        ends = wells[wells.well == producer].active_index.to_numpy() - 1
        end = int(ends[np.argmin(distance[ends])])
        if not np.isfinite(distance[end]):
            continue
        path = [end]
        while predecessors[path[-1]] >= 0:
            path.append(int(predecessors[path[-1]]))
            if len(path) > n:
                raise ValueError("Cycle detected while tracing the path")
        path = np.array(path[::-1])
        name = injector + "__" + producer
        paths[name] = path
        report["injector_to_producer_relative_resistance_paths"][name] = {
            "relative_resistance": float(distance[end]),
            "path_cell_count": len(path),
            "shallowest_depth": float(xyz[2, path].min()),
            "deepest_depth": float(xyz[2, path].max()),
        }
(ROOT / "topology/analysis.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
np.savez_compressed(ROOT / "topology/paths.npz", **paths)
print(
    {
        k: v
        for k, v in report.items()
        if k
        not in {
            "injector_to_producer_relative_resistance_paths",
            "well_connection_components",
        }
    }
)
for producer in ["P11", "P12", "P13", "P14", "P15", "P16"]:
    matches = [
        (k, v)
        for k, v in report["injector_to_producer_relative_resistance_paths"].items()
        if k.endswith("__" + producer)
    ]
    print(
        producer, sorted(matches, key=lambda item: item[1]["relative_resistance"])[:2]
    )
    print(
        "Bottom-water path",
        report["injector_to_producer_relative_resistance_paths"].get(
            "initial_bottom_water__" + producer
        ),
    )
