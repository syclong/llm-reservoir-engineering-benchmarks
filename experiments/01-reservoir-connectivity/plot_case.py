"""Draw plan maps and an I-depth cross section from the blind deck. Optional plotting dependencies."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
import numpy as np

from deck import Grid

ROOT = Path(__file__).resolve().parent
COLORS = ["#ffffff", "#e9e6df", "#dad2c3", "#237c82", "#e69d4d"]
INK = "#182f39"


def draw():
    grid = Grid((ROOT / "inputs/CASE.DATA").read_text(encoding="utf-8"))
    wells, _ = grid.read_wells()
    levels = np.zeros((grid.nz, grid.ny, grid.nx), dtype=int)
    counts = []
    for k in range(1, grid.nz + 1):
        cells = {c for c in grid.active if grid.ijk(c)[2] == k}
        labels, sizes = grid.components(cells & grid.sand)
        counts.append(sorted(sizes, reverse=True))
        rank = {v: n for n, v in enumerate(sorted(range(len(sizes)), key=sizes.__getitem__, reverse=True))}
        for c in cells:
            i, j, _ = grid.ijk(c)
            levels[k - 1, j - 1, i - 1] = (3 + rank[labels[c]]) if c in labels else (1 if sizes else 2)

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": INK, "axes.labelcolor": INK,
                         "xtick.color": "#50616a", "ytick.color": "#50616a", "axes.edgecolor": "#b4bcbf",
                         "font.size": 9})
    fig = plt.figure(figsize=(10, 8.8), facecolor="white")
    gs = fig.add_gridspec(2, 3, height_ratios=(1.72, 1), left=.09, right=.96, top=.87, bottom=.085, hspace=.43, wspace=.22)
    fig.text(.09, .966, "Static interwell connectivity", size=23, weight="bold", va="top")
    fig.text(.09, .917, "Reservoir-quality bodies, open completions and structural relief", size=11, color="#50616a")
    for k in range(grid.nz):
        ax = fig.add_subplot(gs[0, k])
        ax.imshow(levels[k], origin="lower", extent=(.5, grid.nx + .5, .5, grid.ny + .5),
                  cmap=ListedColormap(COLORS), vmin=-.5, vmax=len(COLORS) - .5, interpolation="nearest")
        count_text = " + ".join(str(n) for n in counts[k]) + " cells" if counts[k] else "0 reservoir-quality cells"
        ax.set_title(f"K{k + 1}    {count_text}", fontsize=10.5, weight="bold", loc="left", pad=8)
        for well in wells:
            i, j = well["ij"]
            ax.plot(i, j, "o", mec=INK, mew=1.3, mfc=INK if k + 1 in well["open_k"] else "white", ms=6, zorder=5)
            ax.annotate(well["name"], (i, j), xytext=(5, 3), textcoords="offset points", fontsize=8, weight="bold",
                        bbox=dict(facecolor="white", edgecolor="none", alpha=.80, pad=1))
        ax.set(xticks=[1, 5, 10, 15, 19], yticks=[1, 7, 14, 21, 28], xlabel="I")
        if k == 0:
            ax.set_ylabel("J")
        ax.tick_params(length=3)

    j_section = wells[0]["ij"][1]
    ax = fig.add_subplot(gs[1, :])
    polygons, colors = [], []
    for k in range(1, grid.nz + 1):
        for i in range(1, grid.nx + 1):
            c = grid.cell(i, j_section, k)
            if c not in grid.active:
                continue
            t, b = grid.corners(c), grid.corners(c, True)
            z = [(t[0] + t[2]) / 2, (t[1] + t[3]) / 2, (b[1] + b[3]) / 2, (b[0] + b[2]) / 2]
            polygons.append(list(zip((i - .5, i + .5, i + .5, i - .5), z)))
            colors.append(COLORS[levels[k - 1, j_section - 1, i - 1]])
    ax.add_collection(PolyCollection(polygons, facecolors=colors, edgecolors="#839499", linewidths=.32))
    ax.autoscale_view()
    ax.invert_yaxis()
    ax.set(xlabel="I", ylabel="Depth (m)", xticks=[1, 3, 5, 7, 10, 13, 15, 17, 19])
    ax.set_title(f"Section at J = {j_section}", fontsize=11, weight="bold", loc="left")
    w1 = wells[0]
    for k in w1["open_k"]:
        c = grid.cell(*w1["ij"], k)
        d = grid.top(c)
        ax.plot([w1["ij"][0]] * 2, [d + .8, d + grid.thickness(c) - .8], lw=4, color=INK, solid_capstyle="round")
        ax.annotate(w1["name"], (w1["ij"][0], d), xytext=(6, 4), textcoords="offset points", weight="bold", fontsize=9)
    legend = [Patch(fc=COLORS[3], label="Largest body in each layer"), Patch(fc=COLORS[4], label="Separate body"),
              Patch(fc=COLORS[2], label="Barrier"), Patch(fc=COLORS[1], label="Low-permeability rock"),
              Line2D([], [], marker="o", markersize=6, color="none", mec=INK, mfc=INK, label="Open"),
              Line2D([], [], marker="o", markersize=6, color="none", mec=INK, mfc="white", label="Closed / absent")]
    fig.legend(handles=legend, loc="lower center", bbox_to_anchor=(.52, .009), ncol=6,
               frameon=False, fontsize=8.2, handlelength=1.2, columnspacing=1.25)
    path = ROOT / "evaluation/connectivity.png"
    fig.savefig(path, dpi=190, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    draw()
