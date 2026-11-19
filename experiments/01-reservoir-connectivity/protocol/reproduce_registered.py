"""Prepare a self-contained blind prompt, register a trial, score a reply and verify artifacts."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from deck import blind, REPORT_ONLY
from reference import static_reference
from score import evaluate, parse_answer

ROOT = Path(__file__).resolve().parent
DECK = ROOT / "inputs/CASE.DATA"
PROMPT = ROOT / "prompts/single_step.txt"
REGISTER = ROOT / "protocol/registration.json"
TRUTH = ROOT / "evaluation/reference.json"
REPLY = ROOT / "results/model_reply.json"
SCORE = ROOT / "results/score.json"
CODE = ("deck.py", "reference.py", "score.py", "reproduce.py", "protocol/task.txt")
ORIGINAL = "888f4c59ecf8c3709e9369dea81cffadbb7f2a7534bd7fcad38373d5d8580ff0"


def digest(data):
    return sha256(data).hexdigest()


def read(path):
    return path.read_bytes().decode("utf-8")


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def freeze(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to replace different registered bytes: {path.name}")
    else:
        path.write_bytes(data)


def assemble(text):
    return read(ROOT / "protocol/task.txt").rstrip() + "\n" + text + "END DATA\n"


def prepare(source=None):
    if source:
        original = Path(source).read_bytes()
        if digest(original) != ORIGINAL:
            raise ValueError("Source checksum does not match the registered original")
        masked = blind(original.decode("utf-8-sig"))
        freeze(DECK, masked.encode("utf-8"))
    text = read(DECK)
    prompt = assemble(text).encode("utf-8")
    reference = json_bytes(static_reference(text))
    freeze(PROMPT, prompt)
    freeze(TRUTH, reference)
    fields = dict(model="gpt-6-astra", reasoning_effort="max", messages=1, tools=0, attachments=0,
                  previous_messages=0, original_sha256=ORIGINAL, removed_reporting_keywords=sorted(REPORT_ONLY),
                  masked_deck_sha256=digest(DECK.read_bytes()), prompt_utf8_bytes=len(prompt),
                  prompt_sha256=digest(prompt), reference_sha256=digest(reference),
                  code_sha256={p: digest((ROOT / p).read_bytes()) for p in CODE},
                  primary="reservoir_pair_layers", secondary=["open_completion_pairs", "vertical_interfaces"],
                  score_policy="Counts and labels exact; geometry/fluid depths +/-0.5 m; pressure +/-0.1 bar; rate +/-0.1 sm3/d; schedule +/-0.01 d. Missing, duplicate or unsupported scored claims receive zero. No resampling.")
    if REGISTER.exists():
        registered = json.loads(read(REGISTER))
        if any(registered.get(k) != v for k, v in fields.items()):
            raise ValueError("Registered inputs, reference or scoring code have changed")
    else:
        fields["registered_utc"] = datetime.now(timezone.utc).isoformat()
        freeze(REGISTER, json_bytes(fields))


def score(raw):
    ref = static_reference(read(DECK))
    try:
        answer = parse_answer(raw)
    except ValueError as exc:
        return dict(valid_json=False, parse_error=str(exc), **evaluate(ref, {}))
    return dict(valid_json=True, **evaluate(ref, answer))


def verify():
    prepare()
    raw = REPLY.read_bytes()
    registered = json.loads(read(REGISTER))
    receipt = json.loads(read(ROOT / "results/receipt.json"))
    if digest(raw) != receipt["response_sha256"] or registered["prompt_sha256"] != receipt["prompt_sha256"]:
        raise ValueError("Trial artifact checksum mismatch")
    if receipt["returned_model"] != registered["model"] or receipt["status"] != "completed" or receipt["returned_tools_count"] != 0:
        raise ValueError("Unexpected model or trial state")
    report = score(raw.decode("utf-8"))
    if json.loads(read(SCORE)) != report:
        raise ValueError("Stored scores differ from the regenerated scores")
    print(json.dumps(report["groups"], indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", type=Path, help="Optional unedited, original UTF-8 case")
    rank = sub.add_parser("score")
    rank.add_argument("--reply", type=Path, required=True, help="Exact visible answer to the blind prompt")
    rank.add_argument("--out", type=Path, help="Optional destination for the score JSON")
    sub.add_parser("verify")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source)
        print(PROMPT)
    elif args.command == "score":
        report = score(read(args.reply))
        if args.out:
            freeze(args.out, json_bytes(report))
        print(json.dumps(report["groups"], indent=2))
    else:
        verify()


if __name__ == "__main__":
    main()
