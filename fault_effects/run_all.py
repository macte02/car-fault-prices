"""features → rule tests/validation → model → report, in one go.

    python -m fault_effects.run_all --huutokaupat-db data/huutokaupat.db

Collection (`collect_nettiauto`) is separate because it is slow by design.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def run(*args: str) -> None:
    print("\n$ python -m", " ".join(args), flush=True)
    subprocess.run([sys.executable, "-m", *args], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--huutokaupat-db", default=None)
    ap.add_argument("--boot", default="30")
    a = ap.parse_args()
    run("fault_effects.test_faults")
    run("fault_effects.features", *(["--huutokaupat-db", a.huutokaupat_db] if a.huutokaupat_db else []))
    run("fault_effects.validate", "evaluate")
    run("fault_effects.model", "--boot", a.boot)
    run("fault_effects.chart")
    run("fault_effects.report")


if __name__ == "__main__":
    main()
