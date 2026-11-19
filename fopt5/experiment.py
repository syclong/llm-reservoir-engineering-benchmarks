"""Manage proposals, per-arm context, recoverable records, and JutulDarcy scoring."""
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time

import numpy as np
from . import pso
from .design import ROOT, BASE, RULES, WELLS, canonical, digest, dump, parse_plan, read_json, render, write
from .engine import extract, file_sha
from .settings import model_name, validate_model_name


def utc():
    return datetime.now(timezone.utc).isoformat()


def directory(study, arm, number):
    return Path(study)/arm/f"r{number:02d}"


@contextmanager
def exclusive(study):
    """The operating system releases this lock on process exit, preventing simultaneous dispatch of the same round."""
    study.mkdir(parents=True,exist_ok=True)
    with (study/".study.lock").open("a+b") as lock:
        if not lock.seek(0,2):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def verify_backend(study):
    path=Path(study)/"study.json"
    if path.exists() and read_json(path).get("signature",{}).get("simulator") != "JutulDarcy":
        raise ValueError("This study belongs to a different simulator. Select a new directory for JutulDarcy.")


def history(study, arm):
    verify_backend(study)
    records=[]
    for number in range(1,6):
        folder=directory(study,arm,number)
        if not folder.exists():
            if any(directory(study,arm,k).exists() for k in range(number+1,6)):
                raise ValueError("The round sequence has a gap")
            break
        if not (folder/"record.json").exists():
            raise RuntimeError(f"This round is unsettled. Inspect {folder} and use recover.")
        row=read_json(folder/"record.json")
        if row["round"]!=number or row["arm"]!=arm:
            raise ValueError("Archived round or arm identifier mismatch")
        if row.get("status")=="ok" and (folder/"verification.json").is_file():
            v=read_json(folder/"verification.json")
            if v.get("simulator")!="JutulDarcy" or row["fopt_sm3"]!=v["fopt_sm3"] or row["feedback_sha256"]!=file_sha(folder/"feedback.txt"):
                raise ValueError("A previous score, simulator identifier, or feedback hash failed verification")
        records.append(row)
    return records


def lock_study(study, config, seed):
    verify_backend(study)
    paths=[RULES,BASE,ROOT/"prompts/task.txt",ROOT/"model.json",ROOT/"solver/evaluate.jl",
           ROOT/"solver/Project.toml",ROOT/"solver/Manifest.toml",*sorted((ROOT/"fopt5").glob("*.py"))]
    signature={"protocol":read_json(RULES)["id"], "simulator":"JutulDarcy","seed":seed,
               "files":{p.relative_to(ROOT).as_posix():file_sha(p) for p in paths},
               "runtime_manifest_sha256":file_sha(config["project"]/"Manifest.toml"),
               "julia_exe_sha256":file_sha(config["exe"]),"threads":config["threads"],
               "python":sys.version.split()[0],"numpy":np.__version__,"platform":platform.system()}
    path=Path(study)/"study.json"
    if path.is_file():
        if read_json(path)["signature"]!=signature:
            raise ValueError("The registered source, dependencies, or simulator settings have changed. Select a new study directory.")
    else:
        if any(Path(study).glob("*/r[0-9][0-9]")):
            raise ValueError("Unregistered rounds already exist in this directory")
        write(path,dump({"locked_utc":utc(),"signature":signature}))

def prompt(study,arm,records):
    current=len(records)+1
    head=(ROOT/"prompts/task.txt").read_text(encoding="utf-8")
    parts=[head,f"\nProposal round {current}/5.\n[BEGIN SHARED BASE DATA]",BASE.read_text(encoding="utf-8"),
           "[END SHARED BASE DATA]"]
    if records:
        parts.append("[HISTORY OF THIS ARM] Each row contains the round, status, INJ1, INJ2, PROD1, PROD2, and FOPT (sm³), in that order. NA means unavailable.")
        for h in records:
            p=h.get("plan") or {}
            parts.append(" | ".join([str(h["round"]),h["status"],*[dump(p[w]) if w in p else "NA" for w in WELLS],str(h.get("fopt_sm3","NA"))]))
        if arm=="llm":
            last=records[-1];parts.append("[SIMULATION FEEDBACK FROM THE PRECEDING ROUND]")
            if last["status"]=="ok":
                path=directory(study,arm,last["round"])/"feedback.txt"
                if file_sha(path)!=last["feedback_sha256"]:raise ValueError("The feedback file hash does not match the recorded hash")
                parts.append(path.read_text(encoding="utf-8"))
            else:
                parts.append("No valid production history or grid fields are available for that round. Recorded status = "+last["status"])
    parts.append(f"[END OF INPUT FOR ROUND {current}] Return only the JSON object containing the 28 decisions for the four wells.")
    return "\n".join(parts)+"\n"


def count_budget(text):
    """Apply the fixed study length limit before a proposal is dispatched."""
    limits = read_json(RULES)["LLM"]
    window = limits["token_window"]
    reserve = limits["reserved_output_and_overhead_tokens"]
    size = len(text.encode("utf-8"))
    if not 0 < reserve < window <= 1_000_000 or size + reserve > window:
        raise ValueError("The complete prompt exceeds the study context budget")
    return {"method": "utf8_byte_estimate", "input_count_or_upper_bound": size,
            "reserved_tokens": reserve, "window": window}


def register_model(study, name):
    """Keep one model label throughout the five proposals."""
    name = validate_model_name(name)
    path = Path(study) / "llm" / "model.json"
    if path.is_file():
        if model_name(path) != name:
            raise ValueError("The registered model name has changed")
    else:
        write(path, dump({"model": name}))


def find_model_command():
    executable = shutil.which("llm")
    if executable is None:
        raise FileNotFoundError("Automatic proposals require the llm command on PATH. Use preview and submit for manual proposals.")
    return executable


def model_request(name, text):
    """Send the full prompt on stdin and collect a single text reply on stdout."""
    name = validate_model_name(name)
    executable = find_model_command()
    with tempfile.TemporaryDirectory(prefix="fopt5-model-") as working_dir:
        try:
            result = subprocess.run(
                [executable, "prompt", "--model", name, "--no-stream", "--no-log"],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                cwd=working_dir, shell=False, timeout=900, check=False,
                env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("The local model command timed out") from None
        except OSError:
            raise RuntimeError("Could not launch the local model command") from None
    if result.returncode:
        raise RuntimeError(f"The local model command exited with code {result.returncode}")
    try:
        return result.stdout.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raise ValueError("The local model command must return UTF-8 text") from None


def score_finished(study,arm,number,entry):
    folder=directory(study,arm,number)
    raw=folder/"jutul"
    import tomllib
    with (raw/"complete.toml").open("rb") as handle:
        check=tomllib.load(handle)
    if check["data_sha256"]!=entry["data_sha256"] or file_sha(folder/"MODEL.DATA")!=entry["data_sha256"]:
        raise ValueError("The input DATA hash differs from the solver receipt")
    evidence=extract(raw,entry["plan"],folder)
    entry.update(status="ok",fopt_sm3=evidence["fopt_sm3"],feedback_sha256=file_sha(folder/"feedback.txt"))
    write(folder/"verification.json",dump(evidence))


def round_once(study, arm, records, solver, seed, model=None, manual=None):
    number = len(records) + 1
    if number > 5:
        raise ValueError("The five-round proposal budget is exhausted")
    if arm not in ("llm", "pso"):
        raise ValueError("Unknown study arm")

    if arm == "llm":
        name = model_name() if model is None else validate_model_name(model)
        text = prompt(study, arm, records)
        budget = count_budget(text)
        # An unavailable local client or missing manual file consumes no round.
        if manual is None:
            find_model_command()
        else:
            raw = Path(manual).read_text(encoding="utf-8-sig").strip()

    folder = directory(study, arm, number)
    folder.mkdir(parents=True, exist_ok=False)
    entry = {"round": number, "arm": arm, "proposed_utc": utc(),
             "simulator_calls": 0, "simulator": "JutulDarcy"}
    start = time.monotonic()
    if arm == "llm":
        entry["model"] = name
        entry["context_accounting"] = budget
        write(folder / "prompt.txt", text)
        entry["prompt_sha256"] = file_sha(folder / "prompt.txt")
        if manual is None:
            write(folder / "model_intent.json", dump({"utc": utc(), "model": name, "prompt_sha256": entry["prompt_sha256"]}))
            try:
                raw = model_request(name, text)
            except (OSError, RuntimeError, ValueError) as exc:
                write(folder / "model_error.json", dump({"error": str(exc), "utc": utc()}))
                raise
    else:
        entry["particle_id"] = (number - 1) % pso.N_PARTICLES + 1
        raw = dump(pso.propose(records, seed, number))
    entry["proposal_seconds"] = time.monotonic() - start
    return finish_proposal(study, arm, number, records, solver, folder, entry, raw)


def finish_proposal(study,arm,number,records,solver,folder,entry,raw):
    write(folder/"response.json.txt",raw)
    entry["response_sha256"]=file_sha(folder/"response.json.txt")
    try:
        plan=parse_plan(raw)
    except (ValueError,OverflowError,TypeError) as exc:
        entry.update(status="invalid",reason=str(exc))
    else:
        entry["plan"]=plan
        if any(h.get("plan") and canonical(h["plan"])==canonical(plan) for h in records):
            entry.update(status="duplicate")
        else:
            write(folder/"MODEL.DATA",render(plan))
            entry["data_sha256"]=file_sha(folder/"MODEL.DATA")
            write(folder/"prepared.json",dump(entry))
            begin=time.monotonic()
            try:
                solver.run(folder)
                score_finished(study,arm,number,entry)
            except Exception as exc:
                entry.update(status="simulation_or_qc_failed",reason=str(exc))
            entry["simulator_calls"]=int((folder/"launched.txt").is_file())
            entry["simulation_and_verification_seconds"]=time.monotonic()-begin
    entry["completed_utc"]=utc()
    write(folder/"record.json",dump(entry))
    print(f'{arm} {number}/5 {entry["status"]} {entry.get("fopt_sm3","")}',flush=True)
    return entry
