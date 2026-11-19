"""Read the model label and locate the Julia simulator."""
import json
import os
from pathlib import Path
import re
import shutil
import tomllib

from .design import ROOT


def validate_model_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+-]*(?:/[A-Za-z0-9][A-Za-z0-9._:+-]*)*", name):
        raise ValueError("Invalid model name")
    return name


def model_name(path=None):
    """The model selection file contains one field and a single text value."""
    def single_field(pairs):
        if len(pairs) != 1 or pairs[0][0] != "model":
            raise ValueError("Expected exactly one field named model")
        return dict(pairs)

    source = ROOT / "model.json" if path is None else Path(path)
    with source.open(encoding="utf-8-sig") as stream:
        value = json.load(stream, object_pairs_hook=single_field)
    if not isinstance(value, dict):
        raise ValueError("Expected an object containing the model name")
    return validate_model_name(value["model"])


def local_julia_settings():
    """Read only the Julia section of the optional machine settings file."""
    override = os.getenv("FOPT5_CONFIG")
    if override:
        path = Path(override).expanduser()
    else:
        base = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_CONFIG_HOME")
        path = Path(base or Path.home() / ".config") / "FOPT5" / "settings.toml"
    if not path.is_file():
        if override:
            raise ValueError("The specified Julia settings file does not exist")
        return {}
    with path.open("rb") as stream:
        section = tomllib.load(stream).get("julia", {})
    if not isinstance(section, dict):
        raise ValueError("Expected a table of Julia settings")
    return section


def solver_settings():
    local = local_julia_settings()
    executable = os.getenv("FOPT5_JULIA") or local.get("executable") or shutil.which("julia")
    if not executable or not (resolved := shutil.which(str(executable))):
        raise ValueError("Julia was not found. Set FOPT5_JULIA or add Julia to PATH.")
    project = Path(os.getenv("FOPT5_JULIA_PROJECT") or local.get("project") or ROOT / "solver").resolve()
    if not (project / "Project.toml").is_file() or not (project / "Manifest.toml").is_file():
        raise ValueError("The Julia environment is missing. Run Pkg.instantiate() as described in the README.")
    threads = int(os.getenv("FOPT5_JULIA_THREADS") or local.get("threads", 2))
    if threads < 1:
        raise ValueError("The Julia thread count must be a positive integer")
    depot = os.getenv("FOPT5_JULIA_DEPOT") or local.get("depot") or os.getenv("JULIA_DEPOT_PATH")
    modules = local.get("compiled_modules", True)
    if type(modules) is not bool:
        raise ValueError("compiled_modules must be a Boolean")
    return {"exe": str(Path(resolved).resolve()), "project": project, "depot": depot,
            "threads": threads, "compiled_modules": modules}
