"""Regression tests for Matrix promotion gating, conformance vector integrity, CAS checks, and locking."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("promote_release", ROOT / "tools/promote_release.py")
PROMOTE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROMOTE)


def _init_git_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "dm"
    repo.mkdir()
    shutil.copytree(ROOT / "src", repo / "src")
    shutil.copytree(ROOT / "schemas", repo / "schemas")
    shutil.copytree(ROOT / "tools", repo / "tools")
    shutil.copytree(ROOT / "tests", repo / "tests")
    shutil.copytree(ROOT / ".lley", repo / ".lley")
    shutil.copytree(ROOT / "examples", repo / "examples")
    for fn in ("pyproject.toml", "THIRD_PARTY_NOTICES.md", "README.md", "LICENSE"):
        if (ROOT / fn).is_file():
            shutil.copy2(ROOT / fn, repo / fn)

    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.com")
    git("add", ".")
    git("commit", "-m", "Base release")
    main_sha = git("rev-parse", "HEAD")

    git("checkout", "-b", "nightly")
    (repo / "README.md").write_text("# Nightly change\n", encoding="utf-8")
    git("add", "README.md")
    git("commit", "-m", "Nightly candidate")
    nightly_sha = git("rev-parse", "HEAD")
    return repo, main_sha, nightly_sha


def test_validate_conformance_vectors_rejects_missing_and_malformed(tmp_path):
    with pytest.raises(PROMOTE.PromotionError, match="Missing"):
        PROMOTE.validate_conformance_vectors(tmp_path / "absent.json")

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PROMOTE.PromotionError, match="Malformed"):
        PROMOTE.validate_conformance_vectors(bad_json)

    empty_sec = tmp_path / "empty.json"
    empty_sec.write_text(json.dumps({"programs": [], "expressions": [], "invalid_sources": [], "invalid_expressions": []}), encoding="utf-8")
    with pytest.raises(PROMOTE.PromotionError, match="missing or empty section"):
        PROMOTE.validate_conformance_vectors(empty_sec)

    bad_sha = json.loads((ROOT / "tests/conformance_vectors.json").read_text(encoding="utf-8"))
    bad_sha["programs"][0]["source_sha256"] = "0" * 64
    mismatch = tmp_path / "mismatch.json"
    mismatch.write_text(json.dumps(bad_sha), encoding="utf-8")
    with pytest.raises(PROMOTE.PromotionError, match="source_sha256 mismatch"):
        PROMOTE.validate_conformance_vectors(mismatch)


def test_verify_junit_rejects_incomplete_skipped_and_failed_suites(tmp_path):
    for payload in (
        "",
        "<testsuite tests='0'/>",
        "<testsuite><testcase name='skip'><skipped/></testcase></testsuite>",
        "<testsuite><testcase name='fail'><failure>x</failure></testcase></testsuite>",
        "<testsuite><",
    ):
        p = tmp_path / "r.xml"
        p.write_text(payload, encoding="utf-8")
        with pytest.raises(PROMOTE.PromotionError):
            PROMOTE.verify_junit(p)


def test_promotion_fails_safely_on_incompatible_vectors_moved_branch_and_concurrency(tmp_path):
    repo, main_sha, _nightly_sha = _init_git_repo(tmp_path)

    # 1. Moved main branch CAS mismatch
    with pytest.raises(PROMOTE.PromotionError, match="moved"):
        PROMOTE.promote_release(
            repo_root=repo,
            expected_main_sha="a" * 40,
            lock_path=tmp_path / "p1.lock",
        )

    # 2. Concurrent lock held
    lock = tmp_path / "concurrent.lock"
    with PROMOTE._exclusive_lock(lock):
        with pytest.raises(PROMOTE.PromotionError, match="Concurrent promotion"):
            PROMOTE.promote_release(repo_root=repo, expected_main_sha=main_sha, lock_path=lock)

    # 3. Incompatible conformance vector causes pytest failure and blocks promotion
    vec_file = repo / "tests/conformance_vectors.json"
    vec_data = json.loads(vec_file.read_text(encoding="utf-8"))
    vec_data["programs"][0]["plan_sha256"] = "f" * 64
    vec_file.write_text(json.dumps(vec_data), encoding="utf-8")
    subprocess.check_call(["git", "add", "tests/conformance_vectors.json"], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "Incompatible vector"], cwd=repo)

    with pytest.raises(PROMOTE.PromotionError, match="failed"):
        PROMOTE.promote_release(repo_root=repo, expected_main_sha=main_sha, execute=True, lock_path=tmp_path / "p2.lock")
    assert subprocess.check_output(["git", "rev-parse", "refs/heads/main"], cwd=repo, text=True).strip() == main_sha
