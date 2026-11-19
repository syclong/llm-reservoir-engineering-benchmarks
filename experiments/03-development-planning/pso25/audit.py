"""Replay complete generations and independently integrate oil production from raw JutulDarcy substeps."""
import csv
import math
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import tomllib

from fopt5.design import ROOT, read_json, render
from fopt5.engine import extract, file_sha, require
from fopt5.experiment import directory
from .run import ARM, REGISTERED_FILES, check_record, duplicate_flags, evaluation_id
from .swarm import GENERATIONS, PARTICLES, PROTOCOL, SynchronousSwarm


def best_record(rows):
    valid = [row for row in rows if row["status"] == "ok"]
    return max(valid, key=lambda row: row["fopt_sm3"], default=None)


def audit_raw(folder, row):
    raw = folder / "jutul"
    require((folder / "MODEL.DATA").read_bytes() == render(row["plan"]).encode("utf-8"),
            "The DATA deck cannot be reconstructed from the particle's well locations and BHP schedule")
    with (raw / "complete.toml").open("rb") as handle:
        meta = tomllib.load(handle)
    require(meta["data_sha256"] == row["data_sha256"], "The Julia receipt and DATA hash differ")
    with TemporaryDirectory() as work:
        work = Path(work)
        v = extract(raw, row["plan"], work)
        require(v == read_json(folder / "verification.json") and v["fopt_sm3"] == row["fopt_sm3"],
                "The score or verification report recalculated from the raw outputs differs from the archive")
        for name in ("history.csv", "feedback.txt"):
            require(file_sha(work / name) == file_sha(folder / name), "Production history or final grid fields could not be reproduced exactly")
    # Use a separate standard-library sum to integrate both producers over all accepted substeps.
    with (raw / "steps.csv").open(encoding="utf-8", newline="") as stream:
        rates = csv.DictReader(stream)
        oil = math.fsum(-float(step[f"{w}_qo_m3s"]) * float(step["dt_s"])
                        for step in rates for w in ("PROD1", "PROD2"))
    require(math.isclose(oil, row["fopt_sm3"], rel_tol=0, abs_tol=1e-6), "Independent integration produced a different FOPT")


def audit(study):
    study = Path(study)
    registration = read_json(study / "study.json")
    sig = registration["signature"]
    require(sig["protocol"] == PROTOCOL["id"] and sig["simulator"] == "JutulDarcy", "Protocol or simulator mismatch")
    require(set(sig["files"]) == set(REGISTERED_FILES), "Registered file list is incomplete")
    for name, sha in sig["files"].items():
        require(file_sha(ROOT / name) == sha, f"Registered input or program changed: {name}")
    number = PARTICLES * GENERATIONS
    expected = {f"r{i:02d}" for i in range(1, number + 1)}
    present = {p.name for p in (study / ARM).glob("r*") if p.is_dir()}
    require(present == expected, "The study must contain exactly the 25 registered evaluation directories")
    seen = set()
    previous_scores = []
    swarm = SynchronousSwarm(sig["seed"])
    rows, generations = [], []
    previous_finished = None
    for generation in range(1, GENERATIONS + 1):
        plans = swarm.propose_generation()
        recorded = read_json(study / "generations" / f"g{generation:02d}.json")
        frozen_at = datetime.fromisoformat(recorded["proposed_utc"])
        require(recorded["batch"] == {"generation": generation, "plans": plans,
                                      "previous_generation_scores_sm3": previous_scores},
                "The generation cannot be reproduced from its score history")
        require(previous_finished is None or frozen_at >= previous_finished, "The next generation was registered before the previous one settled")
        batch = []
        for particle, (plan, duplicate) in enumerate(zip(plans, duplicate_flags(plans, seen)), 1):
            folder = directory(study, ARM, evaluation_id(generation, particle))
            row = read_json(folder / "record.json")
            check_record(folder, row, generation, particle, plan, duplicate)
            require(datetime.fromisoformat(row["completed_utc"]) >= frozen_at, "A particle finished before its generation was registered")
            if row["status"] == "ok":
                audit_raw(folder, row)
            batch.append(row)
        rows.extend(batch)
        previous_scores = [row.get("fopt_sm3") for row in batch]
        swarm.observe(previous_scores)
        previous_finished = max(datetime.fromisoformat(row["completed_utc"]) for row in batch)
        best = best_record(batch)
        overall = best_record(rows)
        generations.append({
            "generation": generation, "scores_sm3": previous_scores,
            "calls": sum(row["simulator_calls"] for row in batch),
            "calls_so_far": sum(row["simulator_calls"] for row in rows),
            "best_particle": best["particle_id"] if best else None,
            "generation_best_sm3": best["fopt_sm3"] if best else None,
            "best_so_far_sm3": overall["fopt_sm3"] if overall else None,
            "wall_seconds": (previous_finished - frozen_at).total_seconds(),
        })
    calls = sum(r["simulator_calls"] for r in rows)
    require(calls == len(list((study / ARM).rglob("launched.txt"))) <= number, "The number of solver dispatches is inconsistent with the budget")
    overall = best_record(rows)
    fields = ("generation", "particle_id", "evaluation", "fopt_sm3", "plan")
    summary = {"simulator": "JutulDarcy", "generations": GENERATIONS, "particles": PARTICLES,
               "seed": sig["seed"], "proposals": len(rows), "simulator_calls": calls,
               "successful": sum(r["status"] == "ok" for r in rows),
               "best": {k: overall[k] for k in fields} if overall else None}
    return {"summary": summary, "rows": rows, "generations": generations}
