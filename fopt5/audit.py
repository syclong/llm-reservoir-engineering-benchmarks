"""Audit a study by recomputing scores and fields from archived Julia outputs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from .pso import propose
from .design import ROOT, parse_plan, read_json, render
from .engine import extract, file_sha, require
from .experiment import directory, history, prompt, verify_backend
from .settings import model_name


def audit(study, arm):
    study=Path(study)
    verify_backend(study)
    signature=read_json(study/"study.json")["signature"]
    for name,expected in signature["files"].items():
        require(file_sha(ROOT/name)==expected,"Registered source or base input has changed")
    seen=[]
    scores=[]
    records=history(study,arm)
    registered=model_name(study/"llm/model.json") if arm=="llm" and records else None
    if registered is not None:
        require(registered==model_name(), "The study and release model labels differ")
    for row in records:
        n=row["round"]
        folder=directory(study,arm,n)
        if arm.startswith("llm"):
            require(row.get("model")==registered,"Round model name differs from the study registration")
            require((folder/"prompt.txt").read_bytes()==prompt(study,arm,seen).encode(),"The prompt differs from the history available at that round")
        if "response_sha256" in row:
            response=folder/"response.json.txt"
            require(file_sha(response)==row["response_sha256"],"Proposal hash mismatch")
            if arm=="pso":
                require(parse_plan(response.read_text(encoding="utf-8"))==propose(seen,signature["seed"],n),"The replayed particle proposal differs from its record")
        if row["status"]=="ok":
            plan=parse_plan(response.read_text(encoding="utf-8"))
            deck=folder/"MODEL.DATA"
            require(plan==row["plan"] and deck.read_bytes()==render(plan).encode() and file_sha(deck)==row["data_sha256"],"The DATA deck differs from the recorded plan")
            import tomllib
            with (folder/"jutul/complete.toml").open("rb") as handle:
                require(tomllib.load(handle)["data_sha256"]==file_sha(deck),"The solver receipt refers to a different DATA deck")
            with TemporaryDirectory() as work:
                tmp=Path(work)
                result=extract(folder/"jutul",plan,tmp)
                require(result==read_json(folder/"verification.json") and result["fopt_sm3"]==row["fopt_sm3"],"Reintegrated oil production differs from the registered score")
                for name in ("history.csv","feedback.txt"):
                    require(file_sha(tmp/name)==file_sha(folder/name),"Recomputed production history or final fields differ from the archive")
            scores.append(row["fopt_sm3"])
        seen.append(row)
    return {"simulator":"JutulDarcy","arm":arm,"rounds":len(seen),"verified":len(scores),
            "best_sm3":max(scores) if scores else None}
