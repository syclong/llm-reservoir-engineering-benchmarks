"""Regenerate the six published figures from the experiment archive with no simulator run."""

import argparse
import json
from pathlib import Path
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import colors
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import StrMethodFormatter
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WELLS = ("P11", "P12", "P13", "P14", "P15", "P16")
BASELINE = "baseline_tuned"
ROUND3 = "round3_timing"
ROUND5 = "round5_path_storage"
LAYERS = (208, 219, 249, 270)
INK = "#172f3c"
BASE_COLOR = "#899aa6"
FIT_COLOR = "#087b78"
GRID = "#e2e8eb"
INACTIVE = "#d9e1e6"
WATER_METRIC = "water_rmse_m3_day"
FIELD_WATER_METRIC = "field_producing_water_rmse_m3_day"
ROUND_KEYS = ("baseline", "round1_rock_and_composition", "round2_rock_edits", "round3_rock_edits")


def configure():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK,
        "axes.labelcolor": INK, "axes.edgecolor": "#b3bec4",
        "xtick.color": "#445965", "ytick.color": "#445965",
        "axes.spines.top": False, "axes.spines.right": False,
        "figure.facecolor": "white", "savefig.facecolor": "white",
    })


def read_json(path):
    return json.loads(path.read_bytes())


def load_history(root, case, kind):
    filename = "matched_oil_water.csv" if kind == "well" else "matched_field_oil_water.csv"
    frame = pd.read_csv(root / "evidence" / case / filename, float_precision="round_trip")
    keys = ["well", "end_days"] if kind == "well" else ["end_days"]
    days = frame.end_days.unique()
    if len(days) != 516 or max(days) != 2891 or frame.duplicated(keys).any():
        raise ValueError(f"Incomplete report history in {case}/{filename}")
    if kind == "well" and (set(frame.well) != set(WELLS) or len(frame) != len(WELLS) * len(days)):
        raise ValueError(f"Missing producer reports in {case}/{filename}")
    return frame.sort_values(keys).reset_index(drop=True)


def check_observations(base, candidate):
    columns = ["start_days", "end_days", "qo_obs", "qw_obs"]
    if "well" in base:
        columns += ["well", "status", "watercut_obs"]
    pd.testing.assert_frame_equal(base[columns], candidate[columns], check_exact=True)


def save(fig, output, filename, title, description, dpi=180):
    fig.savefig(output / filename, dpi=dpi, metadata={"Title": title, "Description": description})
    plt.close(fig)


def heading(fig, title, subtitle, left, title_y, subtitle_y):
    fig.text(left, title_y, title, fontsize=18, fontweight="bold", va="top")
    fig.text(left, subtitle_y, subtitle, fontsize=10.5, color="#48606c", va="top")


def history_lines(ax, base, candidate, key, multiplier, round_number, marker_area):
    observed = ax.scatter(base.end_days, base[f"{key}_obs"] * multiplier, s=marker_area,
                          color=INK, alpha=.82, linewidths=0, zorder=3, label="Observed")
    baseline, = ax.plot(base.end_days, base[f"{key}_sim"] * multiplier, color=BASE_COLOR,
                        linewidth=1.25, label="Baseline")
    fitted, = ax.plot(candidate.end_days, candidate[f"{key}_sim"] * multiplier, color=FIT_COLOR,
                      linewidth=1.45, label=f"Round {round_number}")
    ax.grid(axis="y", color=GRID, linewidth=.7)
    ax.set_axisbelow(True)
    ax.set_xlim(0, 2905)
    return [observed, baseline, fitted]


def plot_field(base, candidate, round_number, output):
    check_observations(base, candidate)
    fifth = round_number == 5
    title = f"Round {round_number} field oil and water history match"
    subtitle = "516 report steps over the full 2,891-day history"
    fig, axes = plt.subplots(2, 1, figsize=(13, 7.2), sharex=True)
    fig.subplots_adjust(left=.098, right=.978, bottom=.097, top=.814, hspace=.29)
    heading(fig, title, subtitle, .098, .968, .91)
    for ax, (key, name, code) in zip(axes, (("qo", "oil", "FOPR"), ("qw", "water", "FWPR"))):
        handles = history_lines(ax, base, candidate, key, .001 if fifth else 1, round_number, 10)
        ax.set_title(f"Field {name} production rate ({code})", loc="left", fontsize=11, fontweight="bold")
        ax.set_ylabel("10³ m³/d" if fifth else "m³/d")
        ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    axes[-1].set_xticks([0, 500, 1000, 1500, 2000, 2500, 2891])
    axes[-1].xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    axes[-1].set_xlabel("Elapsed time (days)")
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(.981, .923),
               ncol=3, frameon=False, columnspacing=1.6)
    filename = "field_oil_water_history.png" if fifth else "round3_field_oil_water_history.png"
    save(fig, output, filename, title, f"{subtitle}. Observed, baseline and round {round_number} rates.")


def plot_wells(base, candidate, output):
    check_observations(base, candidate)
    title = "Six-well history match after round 5"
    subtitle = "516 report steps over 2,891 days. Gaps in water cut represent undefined ratios."
    fig, axes = plt.subplots(len(WELLS), 3, figsize=(16, 16), sharex=True)
    fig.subplots_adjust(left=.075, right=.981, bottom=.053, top=.91, wspace=.24, hspace=.42)
    heading(fig, title, subtitle, .075, .982, .95)
    phases = (("qo", "Oil rate (m³/d)", 1), ("qw", "Water rate (m³/d)", 1),
              ("watercut", "Water cut (%)", 100))
    for row, well in enumerate(WELLS):
        a = base[base.well == well]
        b = candidate[candidate.well == well]
        for ax, (key, label, factor) in zip(axes[row], phases):
            handles = history_lines(ax, a, b, key, factor, 5, 8)
            ax.set_title(f"{well}  ·  {label}", loc="left", fontsize=11, fontweight="bold")
            if key != "watercut":
                ax.yaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
    for ax in axes[-1]:
        ax.set_xticks([0, 1000, 2000, 2891])
        ax.xaxis.set_major_formatter(StrMethodFormatter("{x:,.0f}"))
        ax.set_xlabel("Elapsed time (days)")
    fig.legend(handles=handles, loc="upper right", bbox_to_anchor=(.983, .955),
               ncol=3, frameon=False, columnspacing=1.6)
    save(fig, output, "six_well_history_match.png", title, subtitle)


def plot_well_scores(root, output):
    scores = [read_json(root / "evidence" / case / "oil_water_score.json")["full_period"]["per_well"]
              for case in (BASELINE, ROUND5)]
    metrics = (("oil_rmse_m3_day", "Oil-rate RMSE", "m³/d"), (WATER_METRIC, "Water-rate RMSE", "m³/d"),
               ("water_cut_rmse_percentage_points", "Water-cut RMSE", "Percentage points"))
    title = "Full-history error by producer"
    subtitle = "Open-well reports with positive observed liquid production over 2,891 days"
    fig, axes = plt.subplots(1, 3, figsize=(14.4, 4.8))
    fig.subplots_adjust(left=.062, right=.982, bottom=.12, top=.72, wspace=.35)
    heading(fig, title, subtitle, .062, .96, .875)
    positions = np.arange(len(WELLS))
    for ax, (metric, label, unit) in zip(axes, metrics):
        for offset, values, color, name in zip((-.19, .19), scores, (BASE_COLOR, FIT_COLOR), ("Baseline", "Round 5")):
            ax.bar(positions + offset, [values[w][metric] for w in WELLS], width=.35, color=color, label=name)
        ax.set_xticks(positions, WELLS)
        ax.set_ylabel(unit)
        ax.set_title(label, loc="left", fontsize=11, fontweight="bold")
        ax.grid(axis="y", color=GRID, linewidth=.7)
        ax.set_axisbelow(True)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="upper right", bbox_to_anchor=(.983, .89),
               frameon=False, ncol=2)
    save(fig, output, "well_rmse_comparison.png", title, subtitle)


def load_window(root):
    records = {}
    for round_number in (2, 3):
        name = f"round{round_number}_oil_water_comparison_day1281.json"
        report = read_json(root / "evidence" / "partial_runs" / name)
        if not report["partial_window_only"] or report["common_end_day"] != 1281 or report["history_duration_days"] != 2891:
            raise ValueError(f"Unexpected scoring window in {name}")
        for case, record in report["comparison"].items():
            if case in records and records[case] != record:
                raise ValueError(f"Conflicting shared-window data for {case}")
            records[case] = record
    return [records[key] for key in ROUND_KEYS]


def plot_window(records, output):
    series = (("Field", [s[FIELD_WATER_METRIC] for s in records]),
              ("P14", [s["per_well"]["P14"][WATER_METRIC] for s in records]),
              ("P15", [s["per_well"]["P15"][WATER_METRIC] for s in records]))
    title = "Water-rate RMSE in the first three rounds"
    subtitle = "Shared window through day 1,281. Rates in m³/d."
    fig, axes = plt.subplots(1, 3, figsize=(11.8, 4.3), sharey=True)
    fig.subplots_adjust(left=.144, right=.978, bottom=.245, top=.72, wspace=.22)
    heading(fig, title, subtitle, .062, .963, .865)
    for ax, (name, values) in zip(axes, series):
        ax.barh(range(4), values, color=("#788997", "#497ba3", "#b56732", FIT_COLOR), height=.55)
        for y, value in enumerate(values):
            ax.text(value + 4, y, f"{value:.2f}", va="center", fontsize=9)
        ax.set_yticks(range(4), ["Baseline", "Round 1 (main)", "Round 2", "Round 3"])
        ax.set_xlim(0, 270)
        ax.set_xticks([0, 100, 200])
        ax.grid(axis="x", color=GRID, linewidth=.7)
        ax.set_axisbelow(True)
        ax.spines["left"].set_visible(False)
        ax.tick_params(axis="y", length=0)
        ax.set_title(name, loc="left", fontsize=12, fontweight="bold")
    axes[0].invert_yaxis()
    note = ("The field score uses 78 producing reports. Well scores use open reports "
            "with positive observed liquid production.")
    fig.text(.062, .08, note, fontsize=9, color="#48606c")
    save(fig, output, "first_three_rounds_water_rmse.png", title, f"{subtitle} {note}")


def spatial_fields(root):
    sys.path.insert(0, str(root))
    from compositional_tools import array, SHAPE, NCOMP
    base = root / "runs" / "round-00" / "inputs" / "baseline_explicit"
    final = root / "model"
    indices = np.fromfile(root / "native_baseline" / "cell_map.bin", dtype="<i8") - 1
    if indices.min() < 0 or indices.max() >= np.prod(SHAPE) or len(indices) != len(np.unique(indices)):
        raise ValueError("Invalid one-based active-cell map")
    active = np.zeros(np.prod(SHAPE), dtype=bool)
    active[indices] = True
    active = active.reshape(SHAPE)

    def multiplier(key):
        before = array(base / f"{key}.inc", key).reshape(SHAPE)
        after = array(final / f"{key}.inc", key).reshape(SHAPE)
        return np.divide(after, before, out=np.ones(SHAPE), where=active)

    before_z = array(base / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
    after_z = array(final / "ZMF.inc", "ZMF").reshape((NCOMP, *SHAPE))
    values = (100 * (multiplier("PORO") - 1), np.log10(np.sqrt(multiplier("PERMX") * multiplier("PERMY"))),
              np.log10(multiplier("PERMZ")), 100 * (after_z[1] - before_z[1]))
    return active, values


def wellheads(root):
    text = (root / "model" / "WELLS.inc").read_text(encoding="utf-8").split("COMPDAT", 1)[0]
    matches = re.findall(r"(?m)^\s*'([^']+)'\s+'FIELD'\s+(\d+)\s+(\d+)", text)
    coords = {name: (int(i), int(j)) for name, i, j in matches}
    return {name: coords[name] for name in (*WELLS, "I12-W")}


def plot_spatial(root, output):
    active, values = spatial_fields(root)
    markers = wellheads(root)
    title = "Cumulative spatial property changes after round 5"
    subtitle = "Four model layers referenced to the baseline input fields"
    labels = ("Relative porosity change (%)", "Horizontal permeability multiplier (log₁₀)",
              "Vertical permeability multiplier (log₁₀)", "N2C1 mole-fraction change (percentage points)")
    cmap = plt.get_cmap("RdBu_r").with_extremes(bad=INACTIVE)
    fig = plt.figure(figsize=(16.4, 14.2))
    grid = fig.add_gridspec(8, 5, left=.061, right=.953, bottom=.055, top=.902,
                            height_ratios=(.14, 1) * 4, width_ratios=(1, 1, 1, 1, .045),
                            hspace=.245, wspace=.19)
    heading(fig, title, subtitle, .061, .981, .95)
    legend = [Line2D([], [], marker="o", linestyle="none", color=INK, markersize=5, label="Producer"),
              Line2D([], [], marker="^", linestyle="none", color="#785225", markersize=6, label="I12-W injector"),
              Patch(color=INACTIVE, label="Inactive cell")]
    fig.legend(handles=legend, loc="upper right", bbox_to_anchor=(.962, .961), frameon=False,
               ncol=3, columnspacing=1.5)
    for row, (value, label) in enumerate(zip(values, labels)):
        maximum = np.max(np.abs(value[active]))
        unchanged = maximum < 1e-9
        if unchanged:
            value = np.zeros_like(value)
            maximum = 1.0
            label += "  ·  All active cells unchanged"
        norm = colors.TwoSlopeNorm(vmin=-maximum, vcenter=0, vmax=maximum)
        row_header = fig.add_subplot(grid[2 * row, :4])
        row_header.axis("off")
        row_header.text(0, .5, label, va="center", fontsize=12.5, fontweight="bold")
        for col, layer in enumerate(LAYERS):
            ax = fig.add_subplot(grid[2 * row + 1, col])
            layer_data = np.ma.array(value[layer - 1], mask=~active[layer - 1])
            im = ax.imshow(layer_data, origin="lower", extent=(.5, 47.5, .5, 39.5),
                           cmap=cmap, norm=norm, interpolation="none")
            for name, (i, j) in markers.items():
                injector = name == "I12-W"
                color = "#785225" if injector else INK
                ax.plot(i, j, "^" if injector else "o", ms=4 if injector else 3, color=color)
                ax.text(i + .65, j - .95 if injector else j + .57, name, color=color, fontsize=7)
            ax.set_title(f"K = {layer}", fontsize=10, loc="left", pad=2.5)
            ax.spines[["right", "top"]].set_visible(True)
            ax.set_xticks([10, 20, 30, 40])
            ax.set_yticks([5, 15, 25, 35])
            ax.tick_params(labelsize=8, labelbottom=row == 3, labelleft=col == 0, pad=2)
            if col == 0:
                ax.set_ylabel("J index", fontsize=9)
            if row == 3:
                ax.set_xlabel("I index", fontsize=9)
        cax = fig.add_subplot(grid[2 * row + 1, -1])
        if unchanged:
            swatch = matplotlib.cm.ScalarMappable(colors.Normalize(-.5, .5),
                                                 cmap=colors.ListedColormap([cmap(.5)]))
            fig.colorbar(swatch, cax=cax, ticks=[0])
        else:
            fig.colorbar(im, cax=cax)
        cax.tick_params(labelsize=9)
    info = ("The four K-index layers use the native active-cell mask and projected wellheads. "
            "Horizontal permeability uses the geometric mean of the X and Y multipliers.")
    save(fig, output, "round5_spatial_property_changes.png", title, info, dpi=170)


def render(root, output, group="all"):
    output.mkdir(parents=True, exist_ok=True)
    configure()
    base_field = load_history(root, BASELINE, "field")
    if group in ("all", "round-five"):
        plot_field(base_field, load_history(root, ROUND5, "field"), 5, output)
        plot_wells(load_history(root, BASELINE, "well"), load_history(root, ROUND5, "well"), output)
        plot_well_scores(root, output)
        plot_spatial(root, output)
    if group in ("all", "first-three"):
        records = load_window(root)
        third = load_history(root, ROUND3, "field")
        for frame, record in ((base_field, records[0]), (third, records[-1])):
            common = frame[(frame.end_days <= 1281) & (frame.ql_obs > 1e-6)]
            simulated = common[["qo_sim", "qw_sim"]].to_numpy()
            observed = common[["qo_obs", "qw_obs"]].to_numpy()
            expected = [record["field_producing_oil_rmse_m3_day"], record[FIELD_WATER_METRIC]]
            if len(common) != 78 or not np.allclose(np.sqrt(np.mean((simulated - observed) ** 2, axis=0)),
                                                   expected, rtol=1e-9, atol=1e-10):
                raise ValueError("Archived shared-window scores disagree with the field rates")
        plot_window(records, output)
        plot_field(base_field, third, 3, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-root", type=Path, default=ROOT)
    parser.add_argument("--output-dir", type=Path, help="Default to the experiment's results directory.")
    parser.add_argument("--group", choices=("all", "first-three", "round-five"), default="all")
    args = parser.parse_args()
    root = args.experiment_root.resolve()
    render(root, args.output_dir or root / "results", args.group)
