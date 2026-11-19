"""Pass the registered text to one preconfigured, stdin-to-stdout model command and score its answer."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from reproduce import PROMPT, REGISTER, digest, freeze, json_bytes, prepare, score


def now():
    return datetime.now(timezone.utc).isoformat()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="Fresh directory for one independent trial")
    parser.add_argument("adapter", nargs=argparse.REMAINDER, help="Text-only executable followed by its arguments")
    args = parser.parse_args()
    command = args.adapter
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("Supply the command that reads one UTF-8 prompt on stdin and prints the model text on stdout")
    prepare()
    reg = json.loads(REGISTER.read_bytes())
    prompt = PROMPT.read_bytes()
    args.output.mkdir(parents=True, exist_ok=False)
    receipt = dict(started_utc=now(), requested_model=reg["model"], requested_effort=reg["reasoning_effort"],
                   prompt_sha256=digest(prompt), prompt_bytes=len(prompt), adapter_invocations=1)
    freeze(args.output / "intent.json", json_bytes(receipt))
    try:
        process = subprocess.run(command, input=prompt, stdout=subprocess.PIPE, check=False, shell=False)
    except OSError as exc:
        freeze(args.output / "receipt.json", json_bytes({**receipt, "state":"launch_error", "error_type":type(exc).__name__}))
        raise SystemExit("The registered model command could not be started") from None
    raw = process.stdout
    freeze(args.output / "reply.txt", raw)
    receipt.update(completed_utc=now(), process_exit_code=process.returncode, response_sha256=digest(raw))
    if process.returncode:
        freeze(args.output / "receipt.json", json_bytes({**receipt, "state":"adapter_error"}))
        raise SystemExit(process.returncode)
    try:
        report = score(raw.decode("utf-8"))
    except UnicodeDecodeError:
        freeze(args.output / "receipt.json", json_bytes({**receipt, "state":"invalid_utf8"}))
        raise SystemExit("The model command did not return UTF-8") from None
    freeze(args.output / "score.json", json_bytes(report))
    freeze(args.output / "receipt.json", json_bytes({**receipt, "state":"scored", "valid_json":report["valid_json"]}))
    print(json.dumps(report["groups"], indent=2))


if __name__ == "__main__":
    main()
