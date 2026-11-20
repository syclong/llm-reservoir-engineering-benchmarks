"""Plot layer slices from saved candidate input files."""

import argparse
from pathlib import Path
import sys
import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from compositional_tools import fields, array, SHAPE, NCOMP

ARCHIVE = ROOT.parent
parser = argparse.ArgumentParser()
parser.add_argument("best")
parser.add_argument("--layers", nargs="+", type=int, default=[90, 235, 270])
default_output = (
    ROOT / "results" if (ROOT / "candidates").is_dir() else ARCHIVE / "results"
)
parser.add_argument("--output-dir", type=Path, default=default_output)
args = parser.parse_args()
base = ROOT / "candidates/baseline_explicit"
best = ROOT / "candidates" / args.best
cell_map = ROOT / "runs/baseline_tuned/cell_map.bin"
archived_layout = not base.is_dir()
if archived_layout:
    base = ARCHIVE / "runs/round-00/inputs/baseline_explicit"
    cell_map = ARCHIVE / "native_baseline/cell_map.bin"
    if args.best == "round5_path_storage":
        best = ARCHIVE / "model"
    elif args.best == "baseline_explicit":
        best = base
    else:
        matches = list((ARCHIVE / "runs").glob(f"round-*/inputs/{args.best}"))
        if len(matches) != 1:
            raise ValueError(f"No archived field input for {args.best}")
        best = matches[0]


def field_file(directory, keyword):
    # Archived intermediate candidates contain only their cumulative edits.
    edit = directory / (keyword + ".inc")
    return base / (keyword + ".inc") if archived_layout and not edit.is_file() else edit


a = fields(base)
b = {key: array(field_file(best, key), key).reshape(SHAPE) for key in a}
za = array(base / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
zb = array(field_file(best, "ZMF"), "ZMF").reshape((NCOMP, *SHAPE))
indices = np.fromfile(cell_map, dtype=np.int64) - 1
active = np.zeros(np.prod(SHAPE), dtype=bool)
active[indices] = True
active = active.reshape(SHAPE)


def ratio(key):
    out = np.ones(SHAPE)
    np.divide(b[key], a[key], where=active, out=out)
    return out


layers = args.layers
assert all(1 <= layer <= 291 for layer in layers)
values = [
    (100 * (ratio("PORO") - 1), "Porosity change (%)"),
    (
        np.log10(np.sqrt(ratio("PERMX") * ratio("PERMY"))),
        "Horizontal permeability multiplier (log10)",
    ),
    (np.log10(ratio("PERMZ")), "Vertical permeability multiplier (log10)"),
    ((zb[1] - za[1]) * 100, "N2C1 mole fraction change (percentage points)"),
]
plt.rcParams.update(
    {"font.family": "DejaVu Sans", "axes.unicode_minus": False, "font.size": 10}
)
fig, axes = plt.subplots(
    4, len(layers), figsize=(4.7 * len(layers), 15), layout="constrained", squeeze=False
)
wells = {
    "P11": (23, 25),
    "P12": (12, 31),
    "P13": (28, 24),
    "P14": (36, 17),
    "P15": (23, 20),
    "P16": (13, 14),
}
for row, (value, title) in enumerate(values):
    maximum = float(np.max(abs(value[active])))
    if maximum < 1e-9:
        value = np.zeros_like(value)
        maximum = 1.0
        title += " (unchanged)"
    norm = TwoSlopeNorm(vmin=-maximum, vcenter=0, vmax=maximum)
    for col, layer in enumerate(layers):
        ax = axes[row, col]
        data = np.where(active[layer - 1], value[layer - 1], np.nan)
        im = ax.imshow(
            data,
            origin="lower",
            extent=(0.5, 47.5, 0.5, 39.5),
            cmap="RdBu_r",
            norm=norm,
            interpolation="none",
        )
        for well, (i, j) in wells.items():
            ax.plot(i, j, "o", ms=3, color="#202a35")
            ax.text(i + 0.6, j + 0.4, well, fontsize=7, color="#202a35")
        ax.plot(14, 18, "^", ms=4, color="#785225")
        ax.text(14.6, 17.0, "I12-W", fontsize=7, color="#785225")
        ax.set_title(f"K={layer} · {title}", loc="left", fontsize=10)
        ax.set_xlabel("I grid index")
        ax.set_ylabel("J grid index")
    fig.colorbar(im, ax=axes[row, :].tolist(), shrink=0.8, pad=0.015)
fig.suptitle(
    (
        "Input field changes by grid layer (variable depth). Circles mark producers, "
        "triangles mark the I12-W wellhead projection."
    ),
    fontsize=15,
)
out = args.output_dir
out.mkdir(parents=True, exist_ok=True)
figure_name = (
    "round5_spatial_property_changes.png"
    if args.best == "round5_path_storage"
    else f"{args.best}_spatial_property_changes.png"
)
fig.savefig(out / figure_name, dpi=170)
plt.close(fig)
print(out / figure_name)
