"""Run offline Dyadic Matrix CI checks with disposable PostgreSQL and JUnit output."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"


def clean_environment() -> dict[str, str]:
    """Build an isolated offline environment with no host secrets or live DSNs."""
    return {
        "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        "HOME": "/tmp",
        "CI": "true",
        "LANG": "C.UTF-8",
        "TMPDIR": "/tmp",
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }


@contextmanager
def disposable_postgres(env: dict[str, str]):
    """Start an isolated PostgreSQL 17 instance inside the CI container."""
    binary = Path("/usr/lib/postgresql/17/bin")
    if not (binary / "initdb").is_file():
        raise RuntimeError("PostgreSQL 17 binaries not found in CI image.")
    with tempfile.TemporaryDirectory(prefix="dm-ci-pg-", dir=ROOT) as temporary:
        folder = Path(temporary)
        data, sockets = folder / "data", folder / "sockets"
        sockets.mkdir()
        subprocess.run(
            [str(binary / "initdb"), "-D", str(data), "-U", "ci", "-A", "trust", "--no-locale", "-E", "UTF8"],
            env=env,
            check=True,
        )
        options = f"-h 127.0.0.1 -p 5432 -k {sockets} -c fsync=off -c shared_buffers=32MB"
        subprocess.run(
            [str(binary / "pg_ctl"), "-D", str(data), "-l", str(folder / "postgres.log"), "-o", options, "-w", "start"],
            env=env,
            check=True,
        )
        try:
            yield {**env, "DM_TEST_DSN": "postgresql://ci@127.0.0.1:5432/postgres"}
        finally:
            subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-m", "immediate", "-w", "stop"], env=env, check=True)


def verify_junit(report_path: Path) -> None:
    """Reject empty, malformed, zero-passed, failed, errored, or silently skipped runs."""
    if not report_path.is_file():
        raise RuntimeError(f"Missing JUnit report: {report_path}")
    try:
        root = ET.parse(report_path).getroot()
    except ET.ParseError as exc:
        raise RuntimeError(f"Malformed JUnit report {report_path}: {exc}") from exc
    cases = list(root.iter("testcase"))
    failures = sum(1 for c in cases if c.find("failure") is not None)
    errors = sum(1 for c in cases if c.find("error") is not None)
    skipped = sum(1 for c in cases if c.find("skipped") is not None)
    passed = len(cases) - failures - errors - skipped
    print(f"JUnit summary: total={len(cases)} passed={passed} failed={failures} errors={errors} skipped={skipped}", flush=True)
    if not cases or passed == 0 or failures or errors or skipped:
        raise RuntimeError("Invalid test run: every engine test must execute and pass with 0 skips.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", nargs="?", default="engine", choices=("engine",))
    parser.parse_args()
    REPORTS.mkdir(exist_ok=True)
    (ROOT / ".ci-tmp").mkdir(exist_ok=True)
    env = clean_environment()
    report_path = REPORTS / "engine.xml"
    report_path.unlink(missing_ok=True)

    with disposable_postgres(env) as db_env:
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "-ra", "--tb=short", "-p", "no:cacheprovider", f"--junitxml={report_path}"],
            cwd=ROOT,
            env=db_env,
        )
        if res.returncode != 0:
            return res.returncode

    verify_junit(report_path)

    for example in sorted((ROOT / "examples").glob("*.dm")):
        val = subprocess.run(
            [sys.executable, "-m", "dm_engine.cli", "validate", str(example)],
            cwd=ROOT,
            env=env,
        )
        if val.returncode != 0:
            return val.returncode

    print("Dyadic Matrix CI checks passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
