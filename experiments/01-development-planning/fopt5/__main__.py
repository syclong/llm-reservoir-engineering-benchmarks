"""Run or audit the five-round arms and export the exact prompt for the next round."""
import argparse
import csv
import io
from pathlib import Path
from .design import ROOT, RULES, read_json, write, dump
from .engine import Solver
from .experiment import (directory, exclusive, file_sha, history, lock_study, prompt,
                         register_model, round_once, score_finished, utc, verify_backend)
from .settings import model_name, solver_settings

ARMS=("pso","llm")


def scoreboard(study):
    data={arm:history(study,arm) for arm in ARMS}
    rows=[];summary={}
    for arm,records in data.items():
        if not records: continue
        best=None
        for row in records:
            score=row.get("fopt_sm3")
            if score is not None and (best is None or score>best):best=score
            rows.append([arm,row["round"],row["status"],row["simulator_calls"],score,best])
        summary[arm]={"rounds":len(records),"successful":sum(r["status"]=="ok" for r in records),
                      "actual_simulator_calls":sum(r["simulator_calls"] for r in records),
                      "best_fopt_sm3":best,"round5_actual_sm3":records[-1].get("fopt_sm3") if len(records)==5 else None}
    status="waiting_for_two_primary_arms";winner=None;delta=None;ratio=None
    if all(len(data[a])==5 for a in ("pso","llm")):
        if any(r['status'] not in ("ok","invalid","duplicate") for a in ("pso","llm") for r in data[a]):
            status="incomplete_infrastructure_or_qc"
        elif any(summary[a]["best_fopt_sm3"] is None for a in ("pso","llm")):
            status="no_valid_score_in_one_arm"
        else:
            delta=summary["llm"]["best_fopt_sm3"]-summary["pso"]["best_fopt_sm3"]
            denominator=summary["pso"]["best_fopt_sm3"]
            ratio=delta/denominator if denominator else None
            winner="tie" if abs(delta)<=read_json(RULES)["tie_tolerance_sm3"] else ("llm" if delta>0 else "pso")
            status="complete"
    result={"simulator":"JutulDarcy","status":status,"winner":winner,"delta_llm_minus_pso_sm3":delta,"relative_to_pso":ratio,"arms":summary}
    buffer=io.StringIO();w=csv.writer(buffer,lineterminator="\n");w.writerow(["method","round","status","calls","FOPT_sm3","best_so_far_sm3"]);w.writerows(rows)
    write(Path(study)/"rounds.csv",buffer.getvalue());write(Path(study)/"scoreboard.json",dump(result))
    return result


def build_cli():
    cmd=argparse.ArgumentParser(description=__doc__)
    sub=cmd.add_subparsers(dest="op",required=True)
    for name in ("run","submit","prompt","preview","score","status","recover","audit"):
        p=sub.add_parser(name)
        p.add_argument("--study","--run-dir",dest="study",type=Path,default=Path("runs/jutuldarcy_pso"))
        if name not in ("score","status"):
            choices=ARMS if name in ("run","recover","audit") else ("llm",)
            p.add_argument("--arm",choices=choices,default="llm")
        if name in ("run","submit"):
            p.add_argument("--seed",type=int,default=read_json(RULES)["PSO"]["seed"])
            p.add_argument("--timeout","--sim-timeout",type=int,default=900)
        if name=="run":
            p.add_argument("--until",type=int,choices=range(1,6),default=5,help="Run through this registered round number")
        if name in ("prompt","preview"):
            p.add_argument("--output","--save",dest="output",type=Path,required=True)
        if name=="submit":
            p.add_argument("--response",type=Path,required=True)
        if name=="recover":
            p.add_argument("--round",type=int,choices=range(1,6),required=True)
            p.add_argument("--abandon",action="store_true")
            p.add_argument("--original-response",type=Path,help="Original response from the same request")
    return cmd


def recover(args,study):
    folder=directory(study,args.arm,args.round)
    if not folder.is_dir() or (folder/"record.json").exists():
        raise ValueError("Only an existing, unsettled round can be recovered")
    pending=folder/"prepared.json"
    entry=read_json(pending) if pending.exists() else {"arm":args.arm,"round":args.round,"simulator":"JutulDarcy"}
    if args.arm == "llm":
        registered = model_name(study / "llm" / "model.json")
        if registered != model_name() or entry.get("model", registered) != registered:
            raise ValueError("Recovered round has a different registered model name")
        entry["model"] = registered
    entry["simulator_calls"]=int((folder/"launched.txt").exists())
    if args.abandon:
        entry.update(status="interrupted",reason="Interruption recorded")
    elif (folder/"jutul/complete.toml").exists() and pending.exists():
        score_finished(study,args.arm,args.round,entry)
    elif args.original_response:
        # Accept only the original response. Recovery must not request another proposal or dispatch a simulation twice.
        if entry["simulator_calls"] or args.arm=="pso" or not (folder/"prompt.txt").is_file():
            raise ValueError("This round cannot accept a recovered model response")
        from .experiment import finish_proposal
        plan_path=folder/"response.json.txt"
        raw=args.original_response.read_text(encoding="utf-8-sig").strip()
        if plan_path.exists() and plan_path.read_text(encoding="utf-8").strip()!=raw:
            raise ValueError("Recovered text differs from the saved original response")
        prev=[read_json(directory(study,args.arm,k)/"record.json") for k in range(1,args.round)]
        if prompt(study,args.arm,prev)!=(folder/"prompt.txt").read_text(encoding="utf-8"):
            raise ValueError("The original prompt differs from the history of this arm")
        entry["prompt_sha256"]=file_sha(folder/"prompt.txt")
        cfg=solver_settings()
        lock_study(study,cfg,read_json(study/"study.json")["signature"]["seed"])
        worker=Solver(cfg,study)
        try:
            return finish_proposal(study,args.arm,args.round,prev,worker,folder,entry,raw)
        finally:
            worker.close()
    else:
        raise ValueError("No complete simulation receipt is available. Record the interruption or supply the original response from the same request.")
    entry["completed_utc"]=utc()
    write(folder/"record.json",dump(entry))


def main():
    args=build_cli().parse_args()
    study=args.study.resolve()
    verify_backend(study)
    if args.op in ("preview","prompt"):
        rows=history(study,args.arm)
        if len(rows)>=5:
            raise ValueError("This arm has completed all five rounds")
        write(args.output,prompt(study,args.arm,rows))
        print(args.output.resolve())
        return
    if args.op=="audit":
        from .audit import audit
        print(dump(audit(study,args.arm)))
        return
    with exclusive(study):
        if args.op in ("score","status"):
            print(dump(scoreboard(study)))
            return
        if args.op=="recover":
            recover(args,study)
            return
        cfg=solver_settings()
        records=history(study,args.arm)
        limit=args.until if args.op=="run" else min(5,len(records)+1)
        if len(records)>=limit:
            print(dump(scoreboard(study)))
            return
        selected = model_name() if args.arm == "llm" else None
        lock_study(study, cfg, args.seed)
        if selected is not None:
            register_model(study, selected)
        worker=Solver(cfg,study,args.timeout)
        try:
            for _ in range(len(records),limit):
                row=round_once(study,args.arm,records,worker,args.seed,model=selected,manual=getattr(args,"response",None))
                records.append(row)
                scoreboard(study)
                if row["status"]=="simulation_or_qc_failed":
                    raise ValueError(row["reason"])
        finally:
            worker.close()


if __name__=="__main__":
    main()
