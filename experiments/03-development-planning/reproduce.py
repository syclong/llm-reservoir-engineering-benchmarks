"""Replay the recorded five LLM evaluations and 25 particle swarm evaluations."""

import argparse
import csv
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from fopt5.design import WELLS, digest, parse_plan, read_json
from fopt5.engine import require
from fopt5.experiment import prompt
from pso25.audit import audit_raw
from pso25.report import compare_scores
from pso25.swarm import GENERATIONS, PARTICLES, SynchronousSwarm


RESULTS = Path(__file__).resolve().parent / "results"
TABLES = ("comparison.json", "llm_rounds.csv", "particles.csv", "generations.csv")
REPLAY_FILES = (
    "MODEL.DATA", "history.csv", "feedback.txt", "verification.json",
    "jutul/initial.csv", "jutul/final.csv", "jutul/steps.csv", "jutul/complete.toml",
)


def read_table(payload):
    return list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))


def check_text(archive, editions, path, recorded_hash):
    data = archive.read(path)
    require(editions.pop(path) == (recorded_hash, digest(data)), f"Text edition mismatch in {path}")
    return data


def check_run(archive, editions, workspace, arm, number):
    prefix = f"{arm}/r{number:02d}"
    folder = workspace / prefix
    row = json.loads(archive.read(f"{prefix}/record.json"))
    require(row["arm"] == arm and row.get("round", row.get("evaluation")) == number, f"Wrong run record in {prefix}")
    require(row["status"] == "ok" and row["simulator_calls"] == 1, f"Incomplete run in {prefix}")
    for filename in REPLAY_FILES:
        destination = folder / filename
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(f"{prefix}/{filename}"))
    check_text(archive, editions, f"{prefix}/MODEL.DATA", row["data_sha256"])
    check_text(archive, editions, f"{prefix}/feedback.txt", row["feedback_sha256"])
    # Reuse the benchmark's substep integration, shut-in checks and cell-inventory checks.
    audit_raw(folder, row)
    return row


def check_score_row(table_row, run):
    require(float(table_row["fopt_sm3"]) == run["fopt_sm3"], "Score table differs from the simulation")
    require(table_row["status"] == run["status"] and int(table_row["simulator_calls"]) == 1, "Invalid score-table status")
    for well in WELLS:
        plan = [float(table_row[f"{well}_{field}"]) for field in ("I", "J", "BHP1", "BHP2", "BHP3", "BHP4", "BHP5")]
        require(plan == run["plan"][well], f"Score table has a different plan for {well}")


def check_llm(archive, editions, workspace, rounds):
    calls = json.loads(archive.read("llm/calls.json"))
    require(len(calls) == len(rounds) == 5, "Expected five LLM evaluations")
    require(json.loads(archive.read("llm/model.json")) == read_json(RESULTS.parent / "model.json"), "Model label mismatch")
    history = []
    for number, (table_row, call) in enumerate(zip(rounds, calls), 1):
        row = check_run(archive, editions, workspace, "llm", number)
        prefix = f"llm/r{number:02d}"
        reply = archive.read(f"{prefix}/response.json.txt")
        require(parse_plan(reply.decode("utf-8-sig")) == row["plan"], "Original reply and simulated plan differ")
        require(digest(reply) == row["response_sha256"] == call["response_sha256"], "Reply checksum mismatch")
        require(call["round"] == int(table_row["round"]) == number, "LLM round mismatch")
        require(call["input_messages"] == 1 and call["registered_tools"] == 0 and call["response_status"] == "completed",
                "Unexpected LLM interaction record")
        require(call["prompt_sha256"] == row["prompt_sha256"], "Recorded prompt checksum mismatch")
        translated = check_text(archive, editions, f"{prefix}/prompt.txt", row["prompt_sha256"])
        require(translated == prompt(workspace, "llm", history).encode("utf-8"), "English prompt replay mismatch")
        check_score_row(table_row, row)
        # The next English prompt embeds the preceding English feedback.
        history.append(dict(row, feedback_sha256=digest(archive.read(f"{prefix}/feedback.txt"))))
        require(float(table_row["best_so_far_sm3"]) == max(r["fopt_sm3"] for r in history), "LLM incumbent mismatch")
    return max(history, key=lambda r: r["fopt_sm3"])


def check_swarm(archive, editions, workspace, summary, particles, generations):
    require(len(particles) == GENERATIONS * PARTICLES == 25 and len(generations) == GENERATIONS, "Swarm table size mismatch")
    swarm = SynchronousSwarm(summary["seed"])
    previous = []
    runs = []
    for generation, table_row in enumerate(generations, 1):
        plans = swarm.propose_generation()
        batch = json.loads(archive.read(f"pso25/generations/g{generation:02d}.json"))["batch"]
        require(batch == {"generation": generation, "plans": plans, "previous_generation_scores_sm3": previous},
                "Frozen generation differs from the seeded replay")
        scores = []
        for particle, plan in enumerate(plans, 1):
            number = len(runs) + 1
            row = check_run(archive, editions, workspace, "pso25", number)
            saved_plan = json.loads(archive.read(f"pso25/r{number:02d}/plan.json"))
            require(row["generation"] == generation and row["particle_id"] == particle, "Particle order mismatch")
            require(row["plan"] == plan == saved_plan, "Particle plan differs from its submitted plan")
            particle_row = particles[number - 1]
            require((int(particle_row["evaluation"]), int(particle_row["generation"]), int(particle_row["particle_id"]))
                    == (number, generation, particle), "Particle table order mismatch")
            check_score_row(particle_row, row)
            require(float(table_row[f"particle_{particle}_sm3"]) == row["fopt_sm3"], "Generation score mismatch")
            scores.append(row["fopt_sm3"])
            runs.append(row)
        require(int(table_row["generation"]) == generation and int(table_row["calls_so_far"]) == len(runs), "Generation budget mismatch")
        require(float(table_row["generation_best_sm3"]) == max(scores), "Generation best mismatch")
        require(float(table_row["best_so_far_sm3"]) == max(r["fopt_sm3"] for r in runs), "Swarm incumbent mismatch")
        swarm.observe(scores)
        previous = scores
    return max(runs, key=lambda r: r["fopt_sm3"])


def verify():
    with ZipFile(RESULTS / "simulation-results.zip") as archive, TemporaryDirectory() as tmp:
        require(archive.testzip() is None, "Invalid archive checksum")
        for filename in TABLES:
            require(archive.read(filename) == (RESULTS / filename).read_bytes(), f"Archive summary differs for {filename}")
        comparison = json.loads(archive.read("comparison.json"))
        rows = read_table(archive.read("text_editions.csv"))
        editions = {r["path"]: (r["recorded_sha256"], r["english_sha256"]) for r in rows}
        require(len(editions) == len(rows) == 65, "Unexpected text-edition index")
        records = {n for n in archive.namelist() if n.endswith("/record.json")}
        expected = {f"{arm}/r{i:02d}/record.json" for arm, count in (("llm", 5), ("pso25", 25)) for i in range(1, count + 1)}
        require(records == expected, "Unexpected set of recorded runs")
        best_llm = check_llm(archive, editions, Path(tmp), read_table(archive.read("llm_rounds.csv")))
        best_pso = check_swarm(archive, editions, Path(tmp), comparison["pso25"],
                               read_table(archive.read("particles.csv")), read_table(archive.read("generations.csv")))
        require(not editions, "Unused text-edition entries")
        llm = comparison["llm5"]
        require((llm["rounds"], llm["simulator_calls"], llm["successful"]) == (5, 5, 5), "LLM budget mismatch")
        swarm = comparison["pso25"]
        require((swarm["generations"], swarm["particles"], swarm["proposals"], swarm["simulator_calls"], swarm["successful"])
                == (5, 5, 25, 25, 25), "PSO budget mismatch")
        require((best_llm["round"], best_llm["fopt_sm3"], best_llm["plan"]) == (llm["best_round"], llm["best_fopt_sm3"], llm["plan"]),
                "Published best LLM result differs")
        best_fields = ("generation", "particle_id", "evaluation", "fopt_sm3", "plan")
        require({k: best_pso[k] for k in best_fields} == swarm["best"], "Published best PSO result differs")
        outcome = compare_scores(5, 25, best_llm["fopt_sm3"], best_pso["fopt_sm3"], comparison["tie_tolerance_sm3"])
        require(comparison["status"] == "complete" and outcome == comparison["full_budget"], "Final comparison differs")
        print(f"Verified 5 LLM and 25 PSO simulations. Best ten-year oil: {outcome['llm_best_sm3']:,.2f} and {outcome['pso_best_sm3']:,.2f} sm³.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify"])
    parser.parse_args()
    verify()
