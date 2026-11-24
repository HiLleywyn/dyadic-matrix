"""Verify and prepare a reviewed promotion from nightly (parity tracking) to main (release)."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(cmd, cwd=cwd, text=True)
    if res.returncode != 0:
        raise SystemExit(res.returncode)
    return res


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dyadic", type=Path, help="Optional Dyadic checkout to verify vendored parity")
    parser.add_argument("--target-branch", default="main")
    args = parser.parse_args()

    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()
    if dirty:
        print("ERROR: working tree must be clean before promotion check.", file=sys.stderr)
        return 1

    run([sys.executable, "-m", "pytest", "tests/test_conformance.py", "tests/test_boundaries.py", "tests/test_engine.py", "tests/test_argv.py", "tests/test_retries.py", "-q", "-p", "no:cacheprovider"])
    if args.dyadic:
        run([sys.executable, "tools/vendor.py", str(args.dyadic), "--check"])

    print(f"Nightly-to-{args.target_branch} release gates passed cleanly (run full DB suite via CI before merging).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
