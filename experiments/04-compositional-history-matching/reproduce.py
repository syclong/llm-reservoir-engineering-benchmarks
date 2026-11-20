"""Recheck the four full-period oil/water scores with the scorer used in the experiment."""

import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parent
CASES = (
    "baseline_tuned",
    "round3_timing",
    "round4_connectivity",
    "round5_path_storage",
)


def compare(actual, expected, label):
    if (
        isinstance(expected, dict)
        and isinstance(actual, dict)
        and expected.keys() == actual.keys()
    ):
        for key in expected:
            compare(actual[key], expected[key], f"{label}.{key}")
    elif (
        isinstance(expected, list)
        and isinstance(actual, list)
        and len(actual) == len(expected)
    ):
        for index, (value, target) in enumerate(zip(actual, expected)):
            compare(value, target, f"{label}[{index}]")
    elif type(actual) in (int, float) and type(expected) in (int, float):
        if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
            raise ValueError(f"Numeric mismatch at {label}")
    elif type(actual) is not type(expected) or actual != expected:
        raise ValueError(f"Mismatch at {label}")


def verify():
    history = ROOT / "model" / "HISTORY.inc"
    scorer = ROOT / "tools" / "score_oil_water.py"
    summary = {}
    with TemporaryDirectory(prefix="reservoir-score-") as scratch:
        for case in CASES:
            source = ROOT / "evidence" / case
            expected = json.loads((source / "oil_water_score.json").read_bytes())
            work = Path(scratch, case)
            work.mkdir()
            for name in ("well_results_si.csv", "run_validation.toml"):
                shutil.copyfile(source / name, work / name)
            subprocess.run(
                [
                    sys.executable,
                    "-X",
                    "utf8",
                    "-B",
                    str(scorer),
                    expected["candidate"],
                    "--run-dir",
                    str(work),
                    "--history-file",
                    str(history),
                ],
                cwd=scratch,
                stdout=subprocess.DEVNULL,
                check=True,
            )
            actual = json.loads((work / "oil_water_score.json").read_bytes())
            compare(actual, expected, case)
            summary[case] = actual["combined_field_well_nrmse_pct"]
    print(json.dumps({"verified_combined_nrmse_percent": summary}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["verify"])
    parser.parse_args()
    verify()
