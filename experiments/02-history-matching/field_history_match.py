"""Postprocess PUNQ field history from the two completed OPM runs."""
import argparse
import csv
from datetime import date, datetime, time, timedelta
import json
import math
from pathlib import Path

import punq_history_match as hm


# Rate and volume fields are native OPM summary vectors. Convert FWCT to percent for display.
MEASURES = {
    "FOPR": ("SM3/DAY", "oil_rate_sm3_per_day"),
    "FWPR": ("SM3/DAY", "water_rate_sm3_per_day"),
    "FWCT": ("", "water_cut_pct"),
    "FOPT": ("SM3", "cumulative_oil_sm3"),
    "FWPT": ("SM3", "cumulative_water_sm3"),
    "FLPR": ("SM3/DAY", "liquid_rate_sm3_per_day"),
}


def read_case(folder):
    prefix = folder / "output/MODEL"
    receipt = json.loads((folder / "flow_complete.json").read_bytes())
    for ext in ("SMSPEC", "UNSMRY"):
        path = prefix.with_suffix("." + ext)
        hm.require(hm.file_hash(path) == receipt["output_sha256"][path.name], "Raw summary hash mismatch")
    hm.require(hm.file_hash(folder/"MODEL.DATA") == receipt["data_sha256"], "Input deck hash mismatch")
    native = hm.get_vectors(prefix)
    columns = {}
    for stem, (unit, _) in MEASURES.items():
        for key in (stem, stem + "H"):
            matched = [i for i, (_, name, entity, number, stored_unit) in enumerate(native["metadata"])
                       if name == key and entity == "" and number == 0 and stored_unit == unit]
            hm.require(len(matched) == 1, f"Missing or ambiguous field vector {key}")
            factor = 100.0 if stem == "FWCT" else 1.0
            columns[key] = [factor * row[matched[0]] for row in native["data"]]
    # Check the field aggregates at every saved time, including adaptive substeps.
    for i in range(len(native["time"])):
        for suffix, oil, water in (("", "oil", "water"), ("H", "oil_h", "water_h")):
            qo = math.fsum(native[oil][w][i] for w in native["wells"])
            qw = math.fsum(native[water][w][i] for w in native["wells"])
            for key, value in (("FOPR", qo), ("FWPR", qw), ("FLPR", qo + qw)):
                hm.require(math.isclose(value, columns[key+suffix][i], rel_tol=3e-6, abs_tol=0.0002),
                           f"{key+suffix} differs from the seven-well total")
            hm.require(qo + qw > 0, "Field water cut is undefined at zero total liquid production")
            hm.require(abs(columns["FWCT"+suffix][i] - 100*qw/(qo+qw)) < 0.00002,
                       "Field water cut differs from the water/liquid ratio")
    return native["origin"], native["time"], columns


def indices_at(times, days):
    result = []
    for day in days:
        matches = [i for i, t in enumerate(times) if abs(t-day) < 1e-4]
        hm.require(len(matches) == 1, f"Expected one field summary row at day {day}")
        result.append(matches[0])
    return result


def rmse(values, targets):
    return math.sqrt(math.fsum((x-y)**2 for x, y in zip(values, targets, strict=True)) / len(targets))


def make_figure(out, origin, periods, cases, matched):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    plt.rcParams.update({"font.size":10.2, "font.family":"DejaVu Sans",
                         "pdf.fonttype":42, "ps.fonttype":42, "axes.spines.top":False,
                         "axes.spines.right":False, "axes.edgecolor":"#87919a"})
    fig, axes = plt.subplots(2, 2, figsize=(12.0, 7.4), sharex=True)
    cfg = (("FOPR", "Oil production rate", "sm³/day", 1.0),
           ("FWPR", "Water production rate", "sm³/day", 1.0),
           ("FWCT", "Field water cut", "%", 1.0),
           ("FOPT", "Cumulative oil production", "million sm³", 1e6))
    start = datetime.combine(origin, time.min)
    end_dates = [datetime.combine(p, time.min) for p in periods]
    styles = (("#6c7481","--"),("#007380","-"))
    for axis, (key, title, unit, scale) in zip(axes.flat, cfg):
        for (_, times, curves), (color, style) in zip(cases, styles):
            dates = [start + timedelta(days=x) for x in times]
            values = [v/scale for v in curves[key]]
            if key=="FOPT":
                axis.plot([start]+dates, [0.0]+values, color=color, ls=style, lw=1.9)
            else:
                axis.step([start]+dates, [values[0]]+values, where="pre", color=color, ls=style, lw=1.55)
        axis.scatter(end_dates, [v/scale for v in matched[key]["history"]],
                     marker="o", facecolors="none", edgecolors="#ad4b1d", linewidths=1.0, s=21, zorder=4)
        axis.set_title(title, loc="left", fontweight="semibold", fontsize=13, pad=6)
        axis.set_ylabel(unit)
        axis.set_ylim(bottom=0)
        axis.grid(axis="y", color="#d9dfe2", linewidth=.6)
        axis.set_axisbelow(True)
        axis.tick_params(colors="#38434a", labelsize=9)
        axis.set_xticks([datetime(y,1,1) for y in (1967,1971,1975,1979,1983)])
        axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
        axis.set_xlim(start-timedelta(days=75),end_dates[-1]+timedelta(days=110))
    handles = [Line2D([0],[0],ls="",marker="o",mfc="none",mec="#ad4b1d",ms=6,label="History"),
               Line2D([0],[0],color=styles[0][0],ls="--",lw=1.7,label="Baseline model"),
               Line2D([0],[0],color=styles[1][0],lw=2,label="After one update")]
    fig.subplots_adjust(left=.086,right=.977,top=.815,bottom=.074,wspace=.24,hspace=.34)
    fig.text(.086,.952,"PUNQ-S3 field history match",fontsize=20,fontweight="semibold",ha="left",va="center")
    fig.text(.086,.902,"Seven producers  |  52 report intervals  |  1967–1983",fontsize=10.5,color="#47555d")
    fig.legend(handles=handles,loc="center right",bbox_to_anchor=(.982,.914),ncol=3,
               handlelength=2,columnspacing=1.1,frameon=False,fontsize=10)
    fig.savefig(out/"field_history_match.png",dpi=175,facecolor="white")
    fig.savefig(out/"field_history_match.pdf",facecolor="white")
    plt.close(fig)


def analyze(study, plot=False):
    """Rebuild the field metrics and aligned table from both native summary files."""
    study = Path(study).resolve()
    folders=[study/"baseline",study/"candidate"]
    calendars=[hm.period_dates(hm.read(f/"MODEL.DATA")) for f in folders]
    hm.require(calendars[0]==calendars[1], "The two schedules have different report dates")
    edges=calendars[0]
    origin=edges[0]
    days=[(x-origin).days for x in edges[1:]]
    cases=[read_case(f) for f in folders]
    hm.require(all(c[0]==origin and abs(c[1][-1]-days[-1])<1e-4 for c in cases), "Incomplete or mismatched simulation period")
    hits=[indices_at(c[1],days) for c in cases]
    matched={}
    metrics={}
    out=study/"results"
    out.mkdir(parents=True,exist_ok=True)
    for key in MEASURES:
        ref_a,ref_b=([c[2][key+"H"][i] for i in idx] for c,idx in zip(cases,hits))
        hm.require(ref_a==ref_b, f"Historical targets differ between runs for {key}")
        before,after=([c[2][key][i] for i in idx] for c,idx in zip(cases,hits))
        matched[key]={"history":ref_a,"baseline":before,"candidate":after}
        initial, final=rmse(before,ref_a),rmse(after,ref_a)
        metrics[key]={"baseline_rmse":initial,"candidate_rmse":final,
                      "relative_rmse_reduction_pct":100*(1-final/initial) if initial else None,
                      "final_history":ref_a[-1],"final_baseline":before[-1],"final_candidate":after[-1]}
    for rate,total in (("FOPR","FOPT"),("FWPR","FWPT")):
        volume=0.
        for lo,hi,q,v in zip(edges[:-1],edges[1:],matched[rate]["history"],matched[total]["history"],strict=True):
            volume+=q*(hi-lo).days
            hm.require(math.isclose(volume,v,rel_tol=3e-7,abs_tol=.5), f"Historical {total} disagrees with the interval rate integral")
    channels=[(k,s) for k in MEASURES for s in ("history","baseline","candidate")]
    header=["interval_start","interval_end","elapsed_days",*[f"{MEASURES[k][1]}_{s}" for k,s in channels]]
    hm.write(out/"field_history_comparison.csv",hm.csv_text(header,(
        [lo.isoformat(),hi.isoformat(),days[i],*[matched[k][s][i] for k,s in channels]]
        for i,(lo,hi) in enumerate(zip(edges[:-1],edges[1:])))))
    audit={"scope":"field","source":"native OPM field vectors verified against all seven wells",
           "field_water_cut":"100 * sum(water rate) / sum(oil rate + water rate)",
           "rmse":"unweighted over common report endpoints","flowing_report_endpoints":len(days),
           "saved_times":{"baseline":len(cases[0][1]),"candidate":len(cases[1][1])},
           "start":origin.isoformat(),"end":edges[-1].isoformat(),"metrics":metrics}
    hm.write(out/"field_history_metrics.json",json.dumps(audit,ensure_ascii=False,indent=2,allow_nan=False)+"\n")
    if plot:
        make_figure(out,origin,edges[1:],cases,matched)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=Path(__file__).resolve().parent/"study")
    parser.add_argument("--no-plot", action="store_true", help="Export the numbers without drawing a figure")
    args=parser.parse_args()
    metrics=analyze(args.study, plot=not args.no_plot)["metrics"]
    print(json.dumps({k:metrics[k] for k in ("FWCT","FOPR","FWPR","FOPT")},ensure_ascii=False))


if __name__=="__main__":
    main()
