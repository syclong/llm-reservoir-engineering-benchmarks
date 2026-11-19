"""Compare evaluation budgets on a common reservoir and export particle scores, a report, and auditable raw evidence."""
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import zipfile

from fopt5.audit import audit as audit_llm
from fopt5.design import RULES, WELLS, read_json, write
from fopt5.engine import require
from fopt5.experiment import history
from .audit import audit, best_record
from .run import ARM, COMMON_FILES
from .swarm import GENERATIONS, PARTICLES


def compatible(first, second):
    for key in ("simulator", "julia_exe_sha256", "runtime_manifest_sha256", "threads"):
        require(first[key] == second[key], f"The simulation environments differ for {key}")
    for name in COMMON_FILES:
        require(first["files"][name] == second["files"][name], f"The physical input or scoring code differs for {name}")


def compare_scores(llm_calls, pso_calls, llm_score, pso_score, tolerance):
    delta = llm_score - pso_score
    winner = "tie" if abs(delta) <= tolerance else ("llm" if delta > 0 else "pso")
    return {"llm_calls": llm_calls, "pso_calls": pso_calls, "llm_best_sm3": llm_score,
            "pso_best_sm3": pso_score, "llm_minus_pso_sm3": delta,
            "llm_relative_to_pso": delta / pso_score if pso_score else None,
            "pso_relative_to_llm": -delta / llm_score if llm_score else None, "winner": winner}


def save_csv(path, header, rows):
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    write(path, buf.getvalue())


def save_tables(study, result):
    rows = result["rows"]
    static = ["evaluation", "generation", "particle_id", "status", "simulator_calls", "fopt_sm3"]
    design = [f"{w}_{key}" for w in WELLS for key in ("I","J","BHP1","BHP2","BHP3","BHP4","BHP5")]
    save_csv(study / "particles.csv", static + design,
             ([row.get(k) for k in static] + [v for w in WELLS for v in row["plan"][w]] for row in rows))
    keys = ["best_particle","generation_best_sm3","best_so_far_sm3","calls","calls_so_far","wall_seconds"]
    save_csv(study / "generations.csv", ["generation", *(f"particle_{i}_sm3" for i in range(1,PARTICLES+1)), *keys],
             ([g["generation"], *g["scores_sm3"], *(g[k] for k in keys)] for g in result["generations"]))


def format_oil(value):
    return f"{value:,.2f}" if value is not None else "Missing"


def write_report(study, outcome, batch_rows, llm_rows):
    pso, llm = outcome["pso25"]["best"], outcome["llm5"]
    full, equal = outcome["full_budget"], outcome["first_generation_budget"]
    relative = full["llm_relative_to_pso"]
    percent = f"({relative:+.2%})" if relative is not None else " (percentage unavailable because the reference value is zero)"
    lines = ["# Ten-year cumulative oil production with 25 PSO evaluations and 5 LLM evaluations", "",
             "Both arms use the same 3,000-cell reservoir, well spacing and BHP limits, 78% water-cut shut-in rule, and JutulDarcy 0.4.1."
             " Each plan starts from the same initial state and runs for 3,650 days. The score is the highest field cumulative surface oil production within each arm's budget.", "",
             "| Method and budget | Simulator calls | Best FOPT (sm³) | Best found in |",
             "|---|---:|---:|---|",
             f'| LLM (five rounds) | {full["llm_calls"]} | {format_oil(llm["best_fopt_sm3"])} | Round {llm["best_round"]} |',
             f'| Synchronous PSO (initial swarm) | {equal["pso_calls"]} | {format_oil(equal["pso_best_sm3"])} | Generation 1 |',
             f'| Synchronous PSO (five generations) | {full["pso_calls"]} | {format_oil(pso["fopt_sm3"])} | Generation {pso["generation"]}, particle {pso["particle_id"]} |',
             "", f'The best LLM plan minus the best PSO plan is {full["llm_minus_pso_sm3"]:+,.2f} sm³'
                 f'{percent}. The percentage uses the five-generation PSO best as its denominator. The tie tolerance is 1 sm³.', "",
             "## Results by generation", "",
             "| Generation | Particle 1 | Particle 2 | Particle 3 | Particle 4 | Particle 5 | Generation best | Best so far |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for g in batch_rows:
        values = [*g["scores_sm3"], g["generation_best_sm3"], g["best_so_far_sm3"]]
        lines.append("| " + " | ".join([str(g["generation"]), *map(format_oil,values)]) + " |")
    lines.extend(["", "All table entries are in sm³. Generation 1 evaluates the initial swarm. Generations 2 through 5 update and evaluate all five particles."
                  f' The random seed is {outcome["pso25"]["seed"]}. Each generation registers all five plans before any production result is available.'
                  " The global best is updated after the whole generation settles. Both scoring and auditing use rates from the original accepted substeps.",
                  "", "## Best plan from each arm", "",
                  "| Method | Well | I | J | Period 1 (bar) | Period 2 (bar) | Period 3 (bar) | Period 4 (bar) | Period 5 (bar) |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|"])
    for name, plan in (("Synchronous PSO",pso["plan"]),("LLM",llm["plan"])):
        for w in WELLS:
            lines.append("| " + " | ".join([name,w,*map(str,plan[w])]) + " |")
    lines.extend(["","Each of the five absolute BHP targets applies for 730 days. The LLM arm reuses five archived evaluations. All additional solves in the extended experiment belong to synchronous PSO."
                  " PSO updates use cumulative oil from its own previous generations. The LLM also receives production history and final grid fields from its preceding round."
                  " The comparison covers one geological realization and one fixed-seed run.",
                  "", "FOPT by LLM round (sm³), in submission order:  " +
                  ", ".join(format_oil(r.get("fopt_sm3")) for r in llm_rows) + ".",
                  "",f'[Best PSO DATA deck](pso25/r{pso["evaluation"]:02d}/MODEL.DATA) · '
                      '[All 25 plans and scores](particles.csv) · [Generation statistics](generations.csv) · [Score data](comparison.json)'])
    write(study / "comparison-report.md", "\n".join(lines)+"\n")


def archive_results(study, reference, destination):
    destination = Path(destination).resolve()
    require(destination.suffix.lower() == ".zip", "The results archive must have a .zip extension")
    sources = []
    def add(base, prefix, paths):
        for item in paths:
            p = base / item
            if p.is_file():
                sources.append((p, prefix + "/" + item))
    pso_root, llm_root = "runs/jutuldarcy_pso25", "runs/jutuldarcy_pso"
    add(study,pso_root,["study.json","particles.csv","generations.csv","comparison.json","audit_pso25.json","comparison-report.md"])
    add(study,pso_root,[f"generations/g{i:02d}.json" for i in range(1,GENERATIONS+1)])
    add(reference,llm_root,["study.json","llm/model.json","audit_llm.json"])
    julia = ["MODEL.DATA","record.json","verification.json","launched.txt","history.csv","feedback.txt",
             "jutul/initial.csv","jutul/final.csv","jutul/steps.csv","jutul/complete.toml","jutul/error.txt"]
    llm_extras = ["prepared.json","prompt.txt","response.json.txt","model_intent.json","model_error.json"]
    for base,prefix,arm,n,extras in ((study,pso_root,ARM,GENERATIONS*PARTICLES,["plan.json"]),
                                    (reference,llm_root,"llm",5,llm_extras)):
        for i in range(1,n+1):
            add(base,prefix,[f"{arm}/r{i:02d}/{name}" for name in julia+extras])
    destination.parent.mkdir(exist_ok=True,parents=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as tmp:
        tmp_path=Path(tmp.name)
    try:
        with zipfile.ZipFile(tmp_path,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
            for src,name in sources:
                archive.write(src,name)
        with zipfile.ZipFile(tmp_path) as archive:
            require(archive.testzip() is None,"The results archive failed its integrity check")
        os.replace(tmp_path,destination)
    finally:
        tmp_path.unlink(missing_ok=True)


def compare(study, llm_study, archive=None):
    pso = audit(study)
    checked = audit_llm(llm_study,"llm")
    llm_rows = history(llm_study,"llm")
    require(len(llm_rows)==5, "The LLM arm must contain five settled rounds")
    compatible(read_json(study/"study.json")["signature"], read_json(llm_study/"study.json")["signature"])
    llm_best = best_record(llm_rows)
    first = pso["generations"][0]
    require(llm_best is not None and first["generation_best_sm3"] is not None, "No valid scores are available for comparison")
    tolerance = read_json(RULES)["tie_tolerance_sm3"]
    calls = sum(r["simulator_calls"] for r in llm_rows)
    full = compare_scores(calls,pso["summary"]["simulator_calls"],llm_best["fopt_sm3"],pso["summary"]["best"]["fopt_sm3"],tolerance)
    equal = compare_scores(calls,first["calls"],llm_best["fopt_sm3"],first["generation_best_sm3"],tolerance)
    complete = all(r["status"] in ("ok","invalid","duplicate") for r in llm_rows+pso["rows"])
    if not complete:
        full["winner"] = None
    if any(r["status"] not in ("ok","invalid","duplicate") for r in llm_rows+pso["rows"][:PARTICLES]):
        equal["winner"] = None
    outcome = {"status":"complete" if complete else "incomplete_infrastructure_or_qc",
               "pso25":pso["summary"], "llm5":{"rounds":5,"simulator_calls":calls,"successful":checked["verified"],
               "best_round":llm_best["round"],"best_fopt_sm3":llm_best["fopt_sm3"],"plan":llm_best["plan"]},
               "first_generation_budget":equal,"full_budget":full,"tie_tolerance_sm3":tolerance}
    save_tables(study,pso)
    write(study/"audit_pso25.json",json.dumps(pso["summary"],ensure_ascii=False,indent=2)+"\n")
    write(study/"comparison.json",json.dumps(outcome,ensure_ascii=False,indent=2)+"\n")
    write_report(study,outcome,pso["generations"],llm_rows)
    if archive is not None:
        archive_results(study,llm_study,archive)
    return outcome
