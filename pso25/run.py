"""Evaluate a frozen generation in independent Julia workers and report scores after the entire generation settles."""
from concurrent.futures import ThreadPoolExecutor
import platform
import sys
import time
from pathlib import Path

import numpy as np

from fopt5.design import ROOT, canonical, digest, dump, read_json, render, write
from fopt5.engine import Solver, file_sha, require
from fopt5.experiment import directory, exclusive, score_finished, utc
from fopt5.settings import solver_settings
from .swarm import GENERATIONS, PARTICLES, PROTOCOL, SynchronousSwarm

ARM = "pso25"
COMMON_FILES = (
    "protocol.json", "inputs/BASE.DATA", "solver/evaluate.jl", "solver/Project.toml",
    "solver/Manifest.toml", "fopt5/design.py", "fopt5/engine.py", "fopt5/pso.py",
    "fopt5/experiment.py", "fopt5/settings.py",
)
REGISTERED_FILES = (*COMMON_FILES, "pso25/protocol.json", "pso25/swarm.py", "pso25/run.py")


def register(study, cfg, seed, workers):
    signature = {
        "protocol": PROTOCOL["id"], "seed": seed, "simulator": "JutulDarcy",
        "threads": cfg["threads"], "runtime_manifest_sha256": file_sha(cfg["project"] / "Manifest.toml"),
        "julia_exe_sha256": file_sha(cfg["exe"]), "python": sys.version.split()[0],
        "numpy": np.__version__, "platform": platform.system(),
        "files": {name: file_sha(ROOT / name) for name in REGISTERED_FILES},
    }
    path = study / "study.json"
    if path.exists():
        require(read_json(path)["signature"] == signature, "The registered protocol, inputs, or runtime environment have changed")
    else:
        require(not (study / ARM).exists() and not (study / "generations").exists(), "Unregistered study material already exists")
        write(path, dump({"locked_utc": utc(), "initial_parallel_workers": workers, "signature": signature}))


def freeze_generation(study, number, plans, previous_scores):
    path = study / "generations" / f"g{number:02d}.json"
    frozen = {"generation": number, "previous_generation_scores_sm3": previous_scores, "plans": plans}
    if path.exists():
        require(read_json(path)["batch"] == frozen, "The generation of proposals differs from the registered history")
    else:
        write(path, dump({"proposed_utc": utc(), "batch": frozen}))


def duplicate_flags(plans, seen):
    flags = []
    for plan in plans:
        key = canonical(plan)
        flags.append(key in seen)
        seen.add(key)
    return flags


def evaluation_id(generation, particle):
    return (generation - 1) * PARTICLES + particle


def check_record(folder, row, generation, particle, plan, duplicate):
    index = evaluation_id(generation, particle)
    require((row["arm"], row["generation"], row["particle_id"], row["evaluation"]) ==
            (ARM, generation, particle, index), "Evaluation or particle ID mismatch")
    require(row["plan"] == plan == read_json(folder / "plan.json"), "The recorded plan differs from the registered generation")
    require((row["status"] == "duplicate") == duplicate, "Duplicate-proposal status mismatch")
    require(row["simulator_calls"] == int((folder / "launched.txt").exists()), "Solver call count mismatch")
    if row["status"] == "ok":
        verification = read_json(folder / "verification.json")
        require(row["simulator_calls"] == 1 and row["data_sha256"] == file_sha(folder / "MODEL.DATA"),
                "A completed evaluation has an inconsistent deck or dispatch count")
        require(verification["simulator"] == "JutulDarcy" and verification["fopt_sm3"] == row["fopt_sm3"]
                and row["feedback_sha256"] == file_sha(folder / "feedback.txt"), "The score of a completed evaluation is inconsistent")
    return row


def evaluate(study, generation, particle, plan, duplicate, solver):
    index = evaluation_id(generation, particle)
    folder = directory(study, ARM, index)
    result_path = folder / "record.json"
    if result_path.exists():
        return check_record(folder, read_json(result_path), generation, particle, plan, duplicate)
    received = folder / "jutul/complete.toml"
    launched = folder / "launched.txt"
    if launched.exists() and not received.is_file():
        raise RuntimeError(f"Evaluation {index} was already dispatched and has no complete receipt. Inspect the current job before dispatching it again.")
    plan_path = folder / "plan.json"
    if plan_path.exists():
        require(read_json(plan_path) == plan, "Checkpointed particle plan mismatch")
    else:
        write(plan_path, dump(plan))
    row = {"arm": ARM, "generation": generation, "particle_id": particle, "evaluation": index,
           "simulator": "JutulDarcy", "plan": plan, "simulator_calls": 0}
    if duplicate:
        require(not received.exists() and not launched.exists(), "A duplicate proposal has an extra solver record")
        row["status"] = "duplicate"
    else:
        deck = render(plan)
        row["data_sha256"] = digest(deck.encode("utf-8"))
        model_path = folder / "MODEL.DATA"
        if model_path.exists():
            require(file_sha(model_path) == row["data_sha256"], "The existing DATA deck differs from the registered plan")
        else:
            require(not received.exists(), "The solver result has no corresponding input file")
            write(model_path, deck)
        start = time.monotonic()
        try:
            if not received.is_file():
                solver.run(folder)
            require(launched.is_file(), "The completed receipt has no dispatch marker")
            # Use the LLM arm's scoring function to integrate original substeps and check reservoir oil inventory.
            score_finished(study, ARM, index, row)
        except (OSError, RuntimeError, ValueError, KeyError) as exc:
            row.update(status="simulation_or_qc_failed", reason=str(exc))
        row["simulator_calls"] = int(launched.is_file())
        row["simulation_and_verification_seconds"] = time.monotonic() - start
    row["completed_utc"] = utc()
    write(result_path, dump(row))
    return row


def run(study, workers=PARTICLES, seed=PROTOCOL["seed"], timeout=900):
    study = Path(study).resolve()
    require(1 <= workers <= PARTICLES, "The number of parallel workers must be between 1 and 5")
    cfg = solver_settings()
    with exclusive(study):
        register(study, cfg, seed, workers)
        swarm = SynchronousSwarm(seed)
        seen = set()
        previous_scores = []
        solvers = []
        for i in range(workers):
            logdir = study / "workers" / f"w{i+1:02d}"
            logdir.mkdir(parents=True, exist_ok=True)
            solvers.append(Solver(cfg, logdir, timeout))
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for gen in range(1, GENERATIONS+1):
                    plans = swarm.propose_generation()
                    flags = duplicate_flags(plans, seen)
                    freeze_generation(study, gen, plans, previous_scores)
                    # Each worker handles its own files. Fewer workers can evaluate a generation in batches.
                    def run_lane(lane):
                        return [evaluate(study, gen, j+1, plans[j], flags[j], solvers[lane])
                                for j in range(lane, PARTICLES, workers)]
                    futures = [pool.submit(run_lane, i) for i in range(workers)]
                    rows = sorted((row for future in futures for row in future.result()),
                                  key=lambda row: row["particle_id"])
                    previous_scores = [row.get("fopt_sm3") for row in rows]
                    swarm.observe(previous_scores)
                    completed = [score for score in previous_scores if score is not None]
                    print(f"Generation {gen}/{GENERATIONS} complete, {len(completed)}/{PARTICLES} valid. "
                          f"Best FOPT this generation: {max(completed, default=None)} sm³", flush=True)
        finally:
            for solver in solvers:
                solver.close()
