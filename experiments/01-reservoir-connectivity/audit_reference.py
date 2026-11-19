"""Independent NumPy/SciPy check of the frozen reference. Run from the experiment directory."""
import json
from pathlib import Path
import re

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

ROOT = Path(__file__).resolve().parent


def numeric(text, name):
    start = re.search(r"^" + name + r"[ \t]*\n", text, re.M).end()
    tokens = text[start:].split("/", 1)[0].split()
    lengths, values = [], []
    for token in tokens:
        parts = token.split("*")
        lengths.append(int(parts[0]) if len(parts) == 2 else 1)
        values.append(float(parts[-1]))
    return np.repeat(values, lengths)


def components(mask, rock, multipliers, in_layer=False):
    ids = np.arange(mask.size).reshape(mask.shape)
    left, right = [], []
    for axis in range(1 if in_layer else 0, 3):
        low = tuple(slice(None, -1) if d == axis else slice(None) for d in range(3))
        high = tuple(slice(1, None) if d == axis else slice(None) for d in range(3))
        through = mask[low] & mask[high] & (rock[axis][low] > 0) & (rock[axis][high] > 0) & (multipliers[axis][low] > 0)
        left.extend(ids[low][through])
        right.extend(ids[high][through])
    matrix = coo_matrix((np.ones(len(left)), (left, right)), shape=(mask.size, mask.size)).tocsr()
    _, labels = connected_components(matrix, directed=False)
    return np.where(mask, labels.reshape(mask.shape), -1)


def compare(text, ref):
    nx, ny, nz = numeric(text, "DIMENS").astype(int)
    shape = (nz, ny, nx)
    array = lambda name: numeric(text, name).reshape(shape)
    active = array("ACTNUM") > 0
    rock = [array("PERM" + axis) for axis in "ZYX"]
    multipliers = [array("MULT" + axis) for axis in "ZYX"]
    sand = active & (np.minimum(rock[1], rock[2]) >= 1)
    for cutoff in (0.01, 100, 1000):
        np.testing.assert_array_equal(sand, active & (np.minimum(rock[1], rock[2]) >= cutoff))
    layer_components = components(sand, rock, multipliers, in_layer=True)
    all_components = components(active, rock, multipliers)
    faces = numeric(text, "ZCORN").reshape(2 * nz, ny, 2, nx, 2).mean(axis=(2, 4))
    pillars = numeric(text, "COORD").reshape(ny + 1, nx + 1, 2, 3)
    np.testing.assert_allclose(np.diff(pillars[:, :, 0, 0], axis=1), ref["grid"]["dx_m"])
    np.testing.assert_allclose(np.diff(pillars[:, :, 0, 1], axis=0), ref["grid"]["dy_m"])
    np.testing.assert_array_equal(active.sum(axis=(1, 2)), ref["grid"]["active_by_k"])
    top = np.where(active[0], faces[0], np.inf)
    crests = [[int(i + 1), int(j + 1)] for j, i in np.argwhere(np.isclose(top, top.min(), atol=1e-5, rtol=0))]
    assert crests == ref["geology"]["tied_crest_ij"]
    np.testing.assert_allclose(top.min(), ref["geology"]["crest_top_m"])
    for k, layer in enumerate(ref["layers"]):
        counts = np.unique(layer_components[k][sand[k]], return_counts=True)[1]
        assert sorted(counts, reverse=True) == layer["body_sizes"]
        assert sand[k].sum() == layer["high_perm_cells"]
        thickness = (faces[2 * k + 1] - faces[2 * k])[active[k]].mean()
        np.testing.assert_allclose(thickness, layer["mean_thickness_m"], rtol=0, atol=1e-6)
    for k, interface in enumerate(ref["vertical"]):
        possible = active[k] & active[k + 1]
        assert possible.sum() == interface["active_faces"]
        opened = possible & (multipliers[0][k] > 0) & (rock[0][k] > 0) & (rock[0][k + 1] > 0)
        assert opened.sum() == interface["open_faces"]
    spec = text.split("\nWELSPECS\n", 1)[1].split("\n/\n", 1)[0]
    indices = {w: (int(j) - 1, int(i) - 1) for w, i, j in re.findall(r"'([^']+)'\s+'[^']+'\s+(\d+)\s+(\d+)", spec)}
    comp = text.split("\nCOMPDAT\n", 1)[1].split("\n/\n", 1)[0]
    actual = {w: set() for w in indices}
    for w, i, j, k1, k2 in re.findall(r"'([^']+)'\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+'OPEN'", comp):
        for k in range(int(k1) - 1, int(k2)):
            actual[w].add(all_components[k, int(j) - 1, int(i) - 1])
    for p in ref["pairs"]:
        a, b = p["wells"]
        aj, ai = indices[a]
        bj, bi = indices[b]
        same = (layer_components[:, aj, ai] >= 0) & (layer_components[:, aj, ai] == layer_components[:, bj, bi])
        np.testing.assert_array_equal(same, p["same_body_by_k"])
        assert bool(actual[a] & actual[b]) == p["open_completion_link"]


if __name__ == "__main__":
    compare((ROOT / "inputs/CASE.DATA").read_text(encoding="utf-8"), json.loads((ROOT / "evaluation/reference.json").read_bytes()))
    print("Independent geometry, cutoff sensitivity, interfaces and all pair paths verified.")
