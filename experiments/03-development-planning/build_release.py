"""Build a readable, self-contained Python script and a source archive from an explicit file list."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
MODULES = ("__init__", "__main__", "audit", "design", "engine", "experiment", "pso", "settings")
RUNTIME = [*(f"fopt5/{m}.py" for m in MODULES), "model.json","solver/evaluate.jl",
           "solver/Project.toml","solver/Manifest.toml","inputs/BASE.DATA","prompts/task.txt","protocol.json","LICENSE"]
RUNTIME += [f"pso25/{name}" for name in (
    "__init__.py", "__main__.py", "swarm.py", "run.py", "audit.py", "report.py", "protocol.json",
)]
MATERIAL = ["README.md",".gitignore",".gitattributes","requirements.txt","audit_study.py","materialize_prompts.py",
            "build_release.py","docs/experiment-design.md","docs/data-and-software.md","examples/output_format.json",
            "prompts/round_1_complete.txt","prompts/README.md",*(f"prompts/round_{i}_template.txt" for i in range(2,6)),
            "tests/test_protocol.py","tests/test_jutul_pso.py","tests/test_pso25.py","tests/test_pso25_comparison.py"]

HEADER = '''# -*- coding: utf-8 -*-
"""JutulDarcy reservoir planning benchmark with five LLM evaluations and five PSO generations (25 evaluations).

This file includes the readable source, the complete DATA deck, and the Julia dependency lockfile.
python fopt5_llm_loop.py preview --save round1.txt
python fopt5_llm_loop.py pso25 run --workers 5
python fopt5_llm_loop.py run --arm pso
python fopt5_llm_loop.py run --arm llm
python fopt5_llm_loop.py unpack FOPT5_local
"""
from pathlib import Path
import sys
import tempfile

# UTF-8 source files captured when the release was built.
FILES = {
'''
FOOTER = '''
def unpack(target):
    for name, source in FILES.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name in CRLF:
            source = source.replace("\\n", "\\r\\n")
        path.write_bytes(source.encode("utf-8"))


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "unpack":
        if len(sys.argv) != 3:
            raise SystemExit("Usage: unpack NEW_DIRECTORY")
        destination = Path(sys.argv[2]).resolve()
        if destination.exists() and any(destination.iterdir()):
            raise SystemExit("The destination directory must be empty")
        unpack(destination)
        print(destination)
        return
    # Extract the code to a temporary directory. Keep study results at the requested location.
    with tempfile.TemporaryDirectory(prefix="fopt5-src-") as directory:
        unpack(Path(directory))
        adjacent = Path(__file__).resolve().parent / "model.json"
        if adjacent.is_file():
            (Path(directory) / "model.json").write_bytes(adjacent.read_bytes())
        sys.path.insert(0, directory)
        if len(sys.argv)>1 and sys.argv[1]=="pso25":
            del sys.argv[1]
            from pso25.__main__ import main as run
        else:
            from fopt5.__main__ import main as run
        run()


if __name__ == "__main__":
    main()
'''


def standalone():
    chunks=[HEADER]
    crlf=[]
    for name in RUNTIME:
        content=(ROOT/name).read_bytes().decode("utf-8")
        if "\r\n" in content:
            if "\n" in content.replace("\r\n",""):
                raise ValueError(f"Mixed line endings in {name}")
            crlf.append(name)
        content=content.replace("\r\n","\n")
        delimiter="'"*3 if "'"*3 not in content else '"'*3
        if delimiter in content or not content.endswith("\n"):
            chunks.append(f"{name!r}: {content!r},\n")
        else:
            chunks.append(f"{name!r}: r{delimiter}{content}{delimiter},\n")
    chunks.extend(["}\n",f"CRLF = {crlf!r}\n",FOOTER])
    return "".join(chunks).encode("utf-8")


def build(destination, bundle_name="FOPT5_JutulDarcy_PSO.zip"):
    if Path(bundle_name).name != bundle_name or Path(bundle_name).suffix.lower() != ".zip":
        raise ValueError("Use a single .zip filename for the release archive")
    destination.mkdir(parents=True,exist_ok=True)
    app=standalone()
    compile(app,"fopt5_llm_loop.py","exec")
    (destination/"fopt5_llm_loop.py").write_bytes(app)
    bundle=destination/bundle_name
    with zipfile.ZipFile(bundle,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name in sorted(RUNTIME+MATERIAL+["fopt5_llm_loop.py"]):
            data=app if name=="fopt5_llm_loop.py" else (ROOT/name).read_bytes()
            item=zipfile.ZipInfo("FOPT5/"+name,(2026,1,1,0,0,0))
            item.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(item,data,compresslevel=9)
    print(bundle,hashlib.sha256(bundle.read_bytes()).hexdigest())


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"dist")
    parser.add_argument("--bundle-name",default="FOPT5_JutulDarcy_PSO.zip")
    args=parser.parse_args()
    build(args.output,args.bundle_name)
