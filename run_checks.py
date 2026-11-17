"""Verify entry: full V1 regression, joint oracle reconciliation, analytic samples."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

STEPS = (
    [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"],
    [sys.executable, "-B", "group_examples.py", "--check"],
)


def main():
    for step in STEPS:
        completed = subprocess.run(step, cwd=ROOT)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
