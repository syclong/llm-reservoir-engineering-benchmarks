"""Run or audit synchronous five-particle PSO and compare it with the archived five LLM proposals."""
import argparse
from pathlib import Path

from fopt5.design import dump
from .swarm import PARTICLES, PROTOCOL


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="operation", required=True)
    for name in ("run", "audit", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--study", type=Path, default=Path("runs/jutuldarcy_pso25"))
        if name == "run":
            command.add_argument("--workers", type=int, choices=range(1, PARTICLES+1), default=PARTICLES)
            command.add_argument("--seed", type=int, default=PROTOCOL["seed"])
            command.add_argument("--timeout", type=int, default=900)
        if name == "compare":
            command.add_argument("--llm-study", type=Path, default=Path("runs/jutuldarcy_pso"))
            command.add_argument("--archive", type=Path, help="Write the report and the raw evidence from both arms to this ZIP archive")
    args = cli.parse_args()
    study = args.study.resolve()
    if args.operation == "run":
        from .run import run
        run(study, args.workers, args.seed, args.timeout)
    elif args.operation == "audit":
        from .audit import audit
        print(dump(audit(study)["summary"]))
    else:
        from .report import compare
        print(dump(compare(study, args.llm_study.resolve(), args.archive)))


if __name__ == "__main__":
    main()
