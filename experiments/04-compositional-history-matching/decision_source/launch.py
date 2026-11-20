"""Launch the existing Julia/JutulDarcy installation and write experiment logs and results in the workspace."""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("script", type=Path)
parser.add_argument("arguments", nargs="*")
parser.add_argument("--threads", type=int, default=8)
args = parser.parse_args()
config = json.loads(
    (WORKSPACE / "jutuldarcy-setup/network-files/Runtime-Config.json").read_text(
        encoding="utf-8-sig"
    )
)
out = ROOT / "logs" / args.name
out.mkdir(parents=True, exist_ok=False)
env = os.environ.copy()
env.update(
    JULIA_DEPOT_PATH=config["DepotPath"] + ";",
    JULIA_LOAD_PATH="@;@stdlib",
    JULIA_PKG_PRECOMPILE_AUTO="0",
    JULIA_NUM_THREADS=str(args.threads),
    OPENBLAS_NUM_THREADS="4",
)
command = [
    config["JuliaExecutable"],
    "--startup-file=no",
    "--project=" + config["NetworkRoot"] + "\\environment",
    str(args.script.resolve()),
    *args.arguments,
]
start = time.monotonic()
with (out / "simulation_log.txt").open("w", encoding="utf-8") as log:
    process = subprocess.Popen(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    (out / "launch_record.json").write_text(
        json.dumps(
            {
                "start_time": datetime.now().isoformat(),
                "PID": process.pid,
                "command": command,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Julia started. Log directory: " + str(out), flush=True)
    for raw in iter(process.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace")
        log.write(line)
        log.flush()
    code = process.wait()
(out / "exit_record.json").write_text(
    json.dumps(
        {"exit_code": code, "elapsed_seconds": time.monotonic() - start},
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
print("Julia finished with exit code " + str(code), flush=True)
print((out / "simulation_log.txt").read_text(encoding="utf-8")[-12000:])
sys.exit(code)
