"""Verify and execute reviewed promotions from nightly (parity tracking) to main (stable release)."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / ".git/promote-release.lock"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")


class PromotionError(RuntimeError):
    """Raised when a promotion precondition, concurrency lock, or verification gate fails."""


@contextlib.contextmanager
def _exclusive_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    try:
        if os.name == "nt":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                raise PromotionError(f"Concurrent promotion already running (lock {lock_path}): {exc}") from exc
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
            except OSError as exc:
                raise PromotionError(f"Concurrent promotion already running (lock {lock_path}): {exc}") from exc
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


def validate_conformance_vectors(vectors_path: Path) -> dict:
    """Validate structure and required sections of Matrix conformance vectors before promotion."""
    if not vectors_path.is_file():
        raise PromotionError(f"Missing conformance vectors: {vectors_path}")
    try:
        data = json.loads(vectors_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PromotionError(f"Malformed conformance vectors JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise PromotionError("Conformance vectors root must be a JSON object.")
    for key in ("programs", "expressions", "invalid_sources", "invalid_expressions"):
        val = data.get(key)
        if not isinstance(val, list) or not val:
            raise PromotionError(f"Conformance vectors missing or empty section: {key!r}")
    for idx, case in enumerate(data["programs"]):
        if not isinstance(case, dict):
            raise PromotionError(f"Malformed program vector at index {idx}")
        for field in ("id", "source", "source_sha256", "plan_sha256", "step_kinds"):
            if field not in case:
                raise PromotionError(f"Program vector {idx} missing field {field!r}")
        if not _SHA256_RE.fullmatch(str(case["source_sha256"])) or not _SHA256_RE.fullmatch(str(case["plan_sha256"])):
            raise PromotionError(f"Program vector {case['id']!r} has invalid SHA-256 metadata")
        if hashlib.sha256(str(case["source"]).encode("utf-8")).hexdigest() != case["source_sha256"]:
            raise PromotionError(f"Program vector {case['id']!r} source_sha256 mismatch")
        if not isinstance(case["step_kinds"], list) or not case["step_kinds"]:
            raise PromotionError(f"Program vector {case['id']!r} must declare non-empty step_kinds")
    for idx, case in enumerate(data["expressions"]):
        if not isinstance(case, dict) or "expr" not in case or "inputs" not in case or "expected" not in case:
            raise PromotionError(f"Malformed expression vector at index {idx}")
    return data


def verify_junit(report_path: Path) -> dict[str, int]:
    """Require complete non-empty JUnit execution with 0 failures, errors, or skips."""
    if not report_path.is_file():
        raise PromotionError(f"Missing JUnit report: {report_path}")
    try:
        root = ET.parse(report_path).getroot()
    except ET.ParseError as exc:
        raise PromotionError(f"Malformed JUnit report {report_path}: {exc}") from exc
    cases = list(root.iter("testcase"))
    failures = sum(1 for c in cases if c.find("failure") is not None)
    errors = sum(1 for c in cases if c.find("error") is not None)
    skipped = sum(1 for c in cases if c.find("skipped") is not None)
    passed = len(cases) - failures - errors - skipped
    summary = {"total": len(cases), "passed": passed, "failed": failures, "errors": errors, "skipped": skipped}
    if not cases or passed <= 0 or failures or errors or skipped:
        raise PromotionError(f"Incomplete or failing test execution: {summary}")
    return summary


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    res = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)
    if res.returncode != 0:
        detail = (res.stderr or res.stdout or "").strip()
        raise PromotionError(f"Command {' '.join(cmd)} failed ({res.returncode}): {detail}")
    return res


def promote_release(
    *,
    repo_root: Path = ROOT,
    dyadic_root: Path | None = None,
    target_branch: str = "main",
    expected_main_sha: str | None = None,
    execute: bool = False,
    lock_path: Path | None = None,
    vectors_path: Path | None = None,
    junit_path: Path | None = None,
    pytest_suites: tuple[str, ...] = (
        "tests/test_conformance.py",
        "tests/test_boundaries.py",
        "tests/test_engine.py",
        "tests/test_argv.py",
        "tests/test_retries.py",
    ),
) -> dict:
    """Validate conformance, tests, vendor parity, and branch CAS before optional promotion."""
    repo_root = Path(repo_root)
    lock_file = Path(lock_path) if lock_path else (repo_root / ".git/promote-release.lock")
    vec_file = Path(vectors_path) if vectors_path else (repo_root / "tests/conformance_vectors.json")
    xml_file = Path(junit_path) if junit_path else (repo_root / "reports/promote-gate.xml")
    if expected_main_sha is not None and not _SHA40_RE.fullmatch(expected_main_sha):
        raise PromotionError(f"Invalid --expected-main-sha: {expected_main_sha!r}")

    with _exclusive_lock(lock_file):
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo_root, text=True).strip()
        if dirty:
            raise PromotionError("Working tree must be clean before promotion check.")

        head_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_root, text=True).strip()
        target_ref = f"refs/heads/{target_branch}"
        target_exists = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", target_ref], cwd=repo_root
        ).returncode == 0
        target_sha = (
            subprocess.check_output(["git", "rev-parse", target_ref], cwd=repo_root, text=True).strip()
            if target_exists
            else None
        )
        if expected_main_sha is not None and target_sha != expected_main_sha:
            raise PromotionError(
                f"Target branch {target_branch!r} moved: expected {expected_main_sha}, found {target_sha}"
            )
        if target_sha is not None:
            anc = subprocess.run(["git", "merge-base", "--is-ancestor", target_sha, head_sha], cwd=repo_root)
            if anc.returncode != 0:
                raise PromotionError(
                    f"HEAD ({head_sha}) is not a fast-forward descendant of {target_branch} ({target_sha})."
                )

        validate_conformance_vectors(vec_file)

        xml_file.parent.mkdir(parents=True, exist_ok=True)
        xml_file.unlink(missing_ok=True)
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                *pytest_suites,
                "-q",
                "-p",
                "no:cacheprovider",
                f"--junitxml={xml_file}",
            ],
            cwd=repo_root,
        )
        summary = verify_junit(xml_file)

        if dyadic_root is not None:
            run([sys.executable, str(repo_root / "tools/vendor.py"), str(dyadic_root), "--check"], cwd=repo_root)

        if target_sha is not None:
            current_after = subprocess.check_output(["git", "rev-parse", target_ref], cwd=repo_root, text=True).strip()
            if current_after != target_sha:
                raise PromotionError(
                    f"Target branch {target_branch!r} moved during validation ({target_sha} -> {current_after})."
                )

        promoted = False
        if execute:
            cmd = ["git", "update-ref", target_ref, head_sha]
            if target_sha is not None:
                cmd.append(target_sha)
            run(cmd, cwd=repo_root)
            promoted = True

        return {
            "status": "promoted" if promoted else "verified_dry_run",
            "candidate_sha": head_sha,
            "target_branch": target_branch,
            "previous_target_sha": target_sha,
            "summary": summary,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dyadic", type=Path, help="Optional Dyadic checkout to verify vendored parity")
    parser.add_argument("--target-branch", default="main")
    parser.add_argument("--expected-main-sha", help="Fail if target branch head moved from this SHA")
    parser.add_argument("--execute", action="store_true", help="Fast-forward target branch atomically after all gates pass")
    parser.add_argument("--lock-file", type=Path, help="Optional exclusive lock file path")
    args = parser.parse_args(argv)

    try:
        result = promote_release(
            dyadic_root=args.dyadic,
            target_branch=args.target_branch,
            expected_main_sha=args.expected_main_sha,
            execute=args.execute,
            lock_path=args.lock_file,
        )
    except PromotionError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
