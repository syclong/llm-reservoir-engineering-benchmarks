"""Audit a registered study using its raw JutulDarcy outputs."""
import argparse
from pathlib import Path
from fopt5.audit import audit
from fopt5.design import dump

if __name__ == "__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--study",type=Path,default=Path("runs/jutuldarcy_pso"))
    p.add_argument("--arm",choices=("pso","llm"),required=True)
    a=p.parse_args()
    print(dump(audit(a.study,a.arm)))
