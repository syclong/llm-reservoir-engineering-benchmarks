"""Compute near-well and pathway weights on the reservoir grid."""

from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

ROOT = Path(__file__).resolve().parent
SHAPE = (291, 39, 47)


def native_fields(run="baseline_tuned"):
    root = ROOT / "runs" / run
    indices = np.fromfile(root / "cell_map.bin", dtype=np.int64) - 1
    xyz = np.fromfile(root / "centroids.bin").reshape((3, -1), order="F")
    connections = pd.read_csv(root / "well_connections.csv")
    for i, axis in enumerate("xyz"):
        connections[axis] = xyz[i, connections.active_index - 1]
    return indices, xyz, connections


def full_field(active_values, indices, default=0.0):
    out = np.full(np.prod(SHAPE), default, dtype=float)
    out[indices] = active_values
    return out.reshape(SHAPE)


def well_region(xyz, connections, well, radius_m, vertical_padding_m=50.0, cutoff=3.0):
    points = connections[connections.well == well].sort_values("z").drop_duplicates("z")
    if points.empty:
        raise ValueError("No active connections for well " + well)
    x = np.interp(xyz[2], points.z, points.x)
    y = np.interp(xyz[2], points.z, points.y)
    horizontal = ((xyz[0] - x) ** 2 + (xyz[1] - y) ** 2) / radius_m**2
    dz = np.maximum(points.z.min() - xyz[2], np.maximum(xyz[2] - points.z.max(), 0.0))
    distance = horizontal + (dz / vertical_padding_m) ** 2
    weights = np.exp(-0.5 * distance)
    weights[distance > cutoff**2] = 0.0
    return weights


def interwell_region(
    xyz, connections, injector, producer, width_m, depth_range, cutoff=3.0
):
    a = connections[connections.well == injector][["x", "y"]].mean().to_numpy()
    b = connections[connections.well == producer][["x", "y"]].mean().to_numpy()
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("Well coordinates are unavailable")
    direction = b - a
    t = np.clip(
        np.sum((xyz[:2].T - a) * direction, axis=1) / np.dot(direction, direction),
        0.0,
        1.0,
    )
    projection = a + t[:, None] * direction
    horizontal = np.sum((xyz[:2].T - projection) ** 2, axis=1) / width_m**2
    low, high = depth_range
    dz = np.maximum(low - xyz[2], np.maximum(xyz[2] - high, 0.0)) / 50.0
    distance = horizontal + dz**2
    weights = np.exp(-0.5 * distance)
    weights[distance > cutoff**2] = 0.0
    return weights


def path_region(xyz, path, horizontal_radius_m, vertical_radius_m, cutoff=3.0):
    """Return smooth three-dimensional weights around the specified connection path and radii."""
    scale = np.array([horizontal_radius_m, horizontal_radius_m, vertical_radius_m])
    points = xyz[:, np.asarray(path, dtype=int)].T / scale
    tree = cKDTree(points)
    distance, _ = tree.query(xyz.T / scale, workers=4)
    weights = np.exp(-0.5 * distance**2)
    weights[distance > cutoff] = 0.0
    return weights
