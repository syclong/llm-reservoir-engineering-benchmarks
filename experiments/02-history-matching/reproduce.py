"""Verify experiment 02 offline, or initialize a fresh study from its working deck."""
import argparse
import csv
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
import field_history_match as field
import punq_history_match as hm

FILES = ("MODEL.DBG", "MODEL.EGRID", "MODEL.ESMRY", "MODEL.INIT",
         "MODEL.PRT", "MODEL.SMSPEC", "MODEL.UNRST", "MODEL.UNSMRY")
CASES = ("baseline", "candidate")
RESULTS = ROOT / "results"


def load(path):
    return json.loads(Path(path).read_bytes())


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def seed_inputs(work):
    """Write the original inputs to an empty directory for a new OPM run."""
    work = Path(work)
    if work.exists() and (not work.is_dir() or any(work.iterdir())):
        raise ValueError("Choose an empty work directory")
    deck = (ROOT / "inputs/BASE.DATA").read_bytes()
    case = load(ROOT / "inputs/case.json")
    hm.require(hm.sha(deck) == case["deck_sha256"], "Working deck hash mismatch")
    text = deck.decode("utf-8")
    edges = hm.period_dates(text)
    schedule = hm.schedule_targets(text, edges)
    history = hm.targets_table(schedule, edges)
    hm.require(hm.sha(history.encode()) == case["targets_sha256"], "Schedule history hash mismatch")
    (work / "baseline").mkdir(exist_ok=True, parents=True)
    (work / "baseline/MODEL.DATA").write_bytes(deck)
    (work / "case.json").write_bytes((ROOT / "inputs/case.json").read_bytes())
    hm.write(work / "schedule_history.csv", history)


def unpack_native(work, manifest):
    path = ROOT / "evidence/opm-2026.04-outputs.zip"
    hm.require(hm.file_hash(path) == manifest["evidence_sha256"], "Native evidence archive hash mismatch")
    expected = {f"{case}/output/{name}" for case in CASES for name in FILES}
    expected.update(f"{case}/flow_complete.json" for case in CASES)
    descriptors = []
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        hm.require(len(members) == len(expected) and set(members) == expected, "Unexpected native evidence members")
        for key in CASES:
            folder = work / key
            (folder / "output").mkdir(exist_ok=True, parents=True)
            stamp = archive.read(f"{key}/flow_complete.json")
            receipt = json.loads(stamp)
            hm.require(receipt["data_sha256"] == hm.file_hash(folder / "MODEL.DATA"), "Native output refers to another deck")
            hm.require(receipt["exit_code"] == 0 and set(receipt["output_sha256"]) == set(FILES), "Incomplete solver receipt")
            descriptors.append(receipt["solver"])
            for name in FILES:
                raw = archive.read(f"{key}/output/{name}")
                hm.require(hm.sha(raw) == receipt["output_sha256"][name], f"Raw output hash mismatch for {key}/{name}")
                (folder / "output" / name).write_bytes(raw)
            (folder / "flow_complete.json").write_bytes(stamp)
    hm.require(descriptors[0] == descriptors[1] and descriptors[0]["docker_image"] == hm.FLOW_IMAGE
               and descriptors[0]["version"] == "flow 2026.04", "Inconsistent simulator identity")


def near(a, b):
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-9)


def check_changed_cells(original, candidate):
    dims, activity, first = hm.grid(original)
    dims2, active2, second = hm.grid(candidate)
    hm.require(dims == dims2 and activity == active2, "Grid or activity changed")
    changes = {}
    for i, active in enumerate(activity):
        before = tuple(first[k][i] for k in hm.PROPS)
        after = tuple(second[k][i] for k in hm.PROPS)
        if before != after:
            hm.require(active == 1, "An inactive cell was changed")
            cell = (i % dims[0]+1, (i//dims[0]) % dims[1]+1, i//(dims[0]*dims[1])+1)
            changes[cell] = before + after
    records = rows(RESULTS / "changed_cells.csv")
    recorded = {tuple(int(row[a]) for a in "IJK"):
                tuple(float(row[k+"_"+suffix]) for suffix in ("before", "after") for k in hm.PROPS)
                for row in records}
    hm.require(len(recorded) == len(records) and recorded == changes, "Changed-cell table differs from the decks")
    return len(changes)


def check_well_tables(work):
    """Compare archived well rows to rates regenerated from the native output."""
    expected = rows(RESULTS / "paired_oil_water_rates.csv")
    index = {(r["well"],r["report_end"]):r for r in expected}
    hm.require(len(expected) == len(index) == 364, "Expected 364 distinct well observations")
    scores = {r["well"]:r for r in rows(RESULTS / "per_well_comparison.csv")}
    hm.require(set(scores)==set(hm.WELLS), "Incomplete well-score table")
    for case in CASES:
        name = "baseline" if case == "baseline" else "after"
        data = rows(work/case/"matched_history.csv")
        hm.require(len(data)==len(index) and {(r["well"],r["interval_end"]) for r in data}==set(index),
                   "Well or report date mismatch")
        for well in hm.WELLS:
            oil_errors, water_errors, cut_errors = [], [], []
            for r in (v for v in data if v["well"] == well):
                archived = index[(well,r["interval_end"])]
                oil, water, ref_o, ref_w = (float(r[k]) for k in ("oil_sim","water_sim","oil_target","water_target"))
                for value, col in ((oil,case+"_oil"),(water,case+"_water"),(ref_o,"history_oil"),(ref_w,"history_water")):
                    hm.require(near(value,float(archived[col])), f"Archived rate mismatch for {well}/{col}")
                oil_errors.append((oil-ref_o)**2)
                water_errors.append((water-ref_w)**2)
                if ref_o+ref_w > hm.EPS:
                    cut_errors.append((water/(oil+water)-ref_w/(ref_o+ref_w))**2 if oil+water > hm.EPS else 1.0)
            line = scores[well]
            hm.require(len(cut_errors)==int(line["flowing_history_intervals"]), "Flowing interval count mismatch")
            for suffix, errors, factor in (("oil_rmse_sm3_d", oil_errors, 1),("water_rmse_sm3_d",water_errors,1),("watercut_rmse_pp",cut_errors,100)):
                value = factor*math.sqrt(math.fsum(errors)/len(errors))
                hm.require(near(value,float(line[name+"_"+suffix])), f"Well RMSE mismatch for {well}/{suffix}")


def plot_wells(work):
    """Overlay the two native time grids and the 52 historical report endpoints."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.lines import Line2D

    runs = [rows(work / name / "well_curves_all_times.csv") for name in CASES]
    target = rows(work / "baseline/matched_history.csv")
    origin = datetime.fromisoformat(load(work / "case.json")["start"])
    fig, axes = plt.subplots(len(hm.WELLS), 2, figsize=(11.1, 14), sharex=True)
    channels = (("WOPR_sm3_d","oil_target","Surface oil rate (sm³/day)"),
                ("WWPR_sm3_d","water_target","Surface water rate (sm³/day)"))
    for j, well in enumerate(hm.WELLS):
        well_target = [r for r in target if r["well"] == well]
        for i, (column, observed, label) in enumerate(channels):
            axis = axes[j, i]
            for run, color, style in zip(runs, ["#6b7280","#08748d"], ["--","-"]):
                data = [r for r in run if r["well"] == well]
                axis.plot([origin + timedelta(days=float(r["time_days"])) for r in data],
                          [float(r[column]) for r in data], color=color, ls=style, lw=1.4)
            axis.scatter([datetime.fromisoformat(r["interval_end"]) for r in well_target],
                         [float(r[observed]) for r in well_target], s=13, facecolors="none", edgecolors="#bc552d", lw=.8)
            axis.grid(axis="y", alpha=.18)
            axis.spines[["top","right"]].set_visible(False)
            axis.set_ylim(bottom=0)
            if i == 0:
                axis.set_ylabel(well, rotation=0, ha="right", va="center", labelpad=14)
            if j == 0:
                axis.set_title(label, loc="left")
            if j == len(hm.WELLS)-1:
                axis.xaxis.set_major_locator(mdates.YearLocator(4))
                axis.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    handles = [Line2D([0],[0], color="#6b7280", ls="--", label="Baseline"),
               Line2D([0],[0], color="#08748d", label="After one update"),
               Line2D([0],[0], marker="o", ls="", mfc="none", mec="#bc552d", label="Schedule history")]
    fig.suptitle("PUNQ-S3 | One-step history match", x=.1, ha="left")
    fig.legend(handles=handles, loc="upper right", ncol=3, frameon=False)
    fig.subplots_adjust(left=.1, right=.98, bottom=.05, top=.94, hspace=.34, wspace=.18)
    for ext in ("png","pdf"):
        fig.savefig(work/"results"/f"well_history_match.{ext}", dpi=160)
    plt.close(fig)


def verify(work, make_plots=False):
    """Rebuild the exact input message, edited DATA and both scores without inference or simulation."""
    work = Path(work).resolve()
    seed_inputs(work)
    manifest = load(ROOT / "evidence/run.json")
    hm.require(hm.file_hash(ROOT / "punq_history_match.py") == manifest["publication_code_sha256"], "Experiment script hash mismatch")
    hm.require(manifest["model"] == hm.MODEL and manifest["input_messages"] == manifest["formal_proposals"] == 1
               and manifest["registered_tools"] == manifest["attachments"] == manifest["returned_tool_calls"] == 0,
               "Invalid experiment receipt")
    deck, edges, schedule, _ = hm.load_inputs(None, work)
    response = (RESULTS / "edits.json").read_bytes()
    hm.require(hm.sha(response) == manifest["response_sha256"], "Model reply hash mismatch")
    candidate, edits = hm.apply_edits(deck, response.decode("utf-8"))
    hm.require(candidate.encode() == (RESULTS/"CANDIDATE.DATA").read_bytes(), "Edited deck cannot be reconstructed")
    hm.write(work/"candidate/MODEL.DATA", candidate)
    unpack_native(work, manifest)
    sim0, hist0, score0, qc0 = hm.matrices_and_curves(work/"baseline", deck, edges, schedule)
    _, hist1, score1, qc1 = hm.matrices_and_curves(work/"candidate", candidate, edges, schedule)
    hm.require(hist0 == hist1 and len(hist0) == manifest["well_interval_targets"], "The two histories differ")
    hm.require(qc0["active_cells"] == qc1["active_cells"] == 1761 and qc0["restart_snapshots"] == qc1["restart_snapshots"] == 53, "Incomplete reservoir states")
    inputs = (deck, hm.target_plain_text(hist0, edges), sim0, score0)
    current = hm.assemble_prompt(*inputs).encode("utf-8")
    hm.require(current == (ROOT / "prompts/single_step.txt").read_bytes(), "Published prompt mismatch")
    recorded_task = (ROOT / "evidence/recorded_task.txt").read_text(encoding="utf-8").rstrip("\n")
    msg = hm.assemble_prompt(*inputs, task=recorded_task).encode("utf-8")
    hm.require(hm.sha(msg) == manifest["prompt_sha256"],
               "The archived model message cannot be reconstructed")
    (work / "prompt.txt").write_bytes(msg)
    saved = load(RESULTS / "comparison.json")
    hm.require(edits == saved["changed"] and saved["response_sha256"] == hm.sha(response)
               and saved["candidate_data_sha256"] == hm.sha(candidate.encode())
               and saved["prompt_sha256"] == hm.sha(msg), "Score provenance or edit counts differ")
    for values, stage in ((score0,"baseline"),(score1,"candidate")):
        for k in ("watercut_rmse_pp","oil_rate_rmse_sm3_d","water_rate_rmse_sm3_d"):
            hm.require(near(values[k],saved[stage][k]), f"Score mismatch at {stage}/{k}")
        for well in hm.WELLS:
            hm.require(near(values["per_well_watercut_rmse_pp"][well],saved[stage]["per_well_watercut_rmse_pp"][well]),
                       f"Water-cut score mismatch for {well}")
    count = check_changed_cells(deck, candidate)
    independent = load(RESULTS / "independent_audit.json")
    hm.require(independent["unique_changed_active_cells"] == count and independent["porosity_changed"] == edits["porosity_cells_changed"]
               and independent["permeability_changed"] == edits["permeability_cells_changed"], "Active-cell audit mismatch")
    check_well_tables(work)
    reduction = score0["watercut_rmse_pp"] - score1["watercut_rmse_pp"]
    hm.require(near(reduction, saved["reduction_pp"]) and near(100*reduction/score0["watercut_rmse_pp"], saved["relative_reduction_pct"])
               and saved["improved"] == (reduction > 0), "The reported improvement differs from the raw scores")
    comparison = {"baseline":score0, "candidate":score1, "reduction_pp":reduction,
                  "relative_reduction_pct":100*reduction/score0["watercut_rmse_pp"], "improved":reduction>0, "changed":edits,
                  "candidate_data_sha256":hm.sha(candidate.encode()), "response_sha256":hm.sha(response),
                  "prompt_sha256":hm.sha(msg),"history_checks_passed":True,"candidate_report_snapshots":qc1["restart_snapshots"]}
    hm.write(work/"comparison.json", hm.as_json(comparison))
    # This copy of the archived answer lets the normal harness reuse the recorded round.
    hm.write(work/"proposal/response.txt", response.decode("utf-8"))
    hm.write(work/"proposal/intent.json", hm.as_json({"mode":"offline_replay","model":hm.MODEL,
             "prompt_sha256":hm.sha(msg),"tools":[],"attachments":[]}))
    hm.verify_delivered_reply(work/"proposal",response.decode("utf-8"),hm.sha(msg))
    original_receipt = (ROOT/"evidence/recorded_prompt_receipt.json").read_bytes()
    input_receipt = json.loads(original_receipt)
    hm.require(input_receipt["sha256"]==hm.sha(msg) and input_receipt["model"]==manifest["model"]
               and input_receipt["attachments"]==input_receipt["tools"]==[] and input_receipt["input_messages"]==1,
               "The original prompt receipt did not pass verification")
    (work/"prompt_receipt.json").write_bytes(original_receipt)
    new_field = field.analyze(work, plot=make_plots)
    recorded_field = load(RESULTS / "field_history_metrics.json")
    for k in field.MEASURES:
        for label, number in new_field["metrics"][k].items():
            old = recorded_field["metrics"][k][label]
            hm.require((number is None and old is None) or (number is not None and old is not None and near(number,old)),
                       f"Field comparison mismatch at {k}/{label}")
    hm.require((work/"results/field_history_comparison.csv").read_bytes() == (RESULTS/"field_history_comparison.csv").read_bytes(),
               "Field report table differs from archive")
    if make_plots:
        plot_wells(work)
    return {"accepted_proposals":1,"native_summaries_checked":2,"well_interval_pairs":len(hist0),
            "well_balanced_before_pp":score0["watercut_rmse_pp"],"well_balanced_after_pp":score1["watercut_rmse_pp"],
            "field_before_pp":new_field["metrics"]["FWCT"]["baseline_rmse"],
            "field_after_pp":new_field["metrics"]["FWCT"]["candidate_rmse"],"changed_active_cells":count}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest="command",required=True)
    init=sub.add_parser("init",help="Initialize an empty directory for a fresh simulation or model run")
    init.add_argument("--work",type=Path,required=True)
    replay=sub.add_parser("verify",help="Recompute the recorded experiment from its bundled native outputs")
    replay.add_argument("--work",type=Path,help="Keep regenerated files in this empty directory")
    replay.add_argument("--plots",action="store_true",help="Regenerate both figures with Matplotlib in --work")
    args=parser.parse_args()
    if args.command=="init":
        seed_inputs(args.work)
        print(args.work.resolve())
        return
    if args.work:
        print(hm.as_json(verify(args.work,args.plots)))
    else:
        if args.plots:
            parser.error("Supply --work to keep the regenerated figures")
        with tempfile.TemporaryDirectory(prefix="punq-offline-replay-") as temp:
            print(hm.as_json(verify(Path(temp))))


if __name__=="__main__":
    main()
