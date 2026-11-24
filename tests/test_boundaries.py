"""Public release boundary and offline CI hygiene checks for dyadic-matrix."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PRIVATE = re.compile(
    r"\bdyadic_core\b|\bdyadic_server\b|dyadic-api\b|dyadic-blackbox|postgresql://ci@|BEGIN PRIVATE KEY",
    re.I,
)


def test_public_engine_contains_no_private_dyadic_or_credential_leaks():
    findings = []
    for folder in (ROOT / "src", ROOT / "schemas", ROOT / "examples", ROOT / "docs"):
        for path in sorted(folder.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".sql", ".json", ".dm", ".md", ".sh", ".ps1", ".txt"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN_PRIVATE.search(line):
                    findings.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()[:120]}")
    assert not findings, "Private Dyadic internals or credentials leaked into public dm:\n" + "\n".join(findings)


def test_pipeline_is_offline_secret_free_and_pinned():
    cfg = json.loads((ROOT / ".lley/pipeline.json").read_text(encoding="utf-8"))
    assert cfg["version"] == 1
    assert cfg["triggers"] == {"push": True, "tags": False, "manual": True}
    assert len(cfg["stages"]) == 1
    stage = cfg["stages"][0]
    assert stage["id"] == "engine"
    assert stage["image"].startswith("sha256:") and len(stage["image"]) == 71
    assert not stage.get("secrets") and not stage.get("network") and not stage.get("deploy")
    assert stage["reports"] == [{"path": "reports/engine.xml", "format": "junit"}]


def test_ci_environment_drops_host_secrets_and_live_dsns():
    sys.path.insert(0, str(ROOT / ".lley"))
    import importlib.util
    spec = importlib.util.spec_from_file_location("dm_ci_run", ROOT / ".lley/run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = os.environ.get("DM_DATABASE_URL")
    os.environ["DM_DATABASE_URL"] = "postgresql://prod:secret@db/prod"
    try:
        clean = mod.clean_environment()
        assert "DM_DATABASE_URL" not in clean
        assert "DM_TEST_DSN" not in clean
    finally:
        if old is None:
            os.environ.pop("DM_DATABASE_URL", None)
        else:
            os.environ["DM_DATABASE_URL"] = old


def test_license_and_schema_files_exist_with_valid_hashes():
    assert "MIT License" in (ROOT / "src/dm_engine/LICENSE").read_text(encoding="utf-8")
    assert (ROOT / "THIRD_PARTY_NOTICES.md").is_file()
    schema_bytes = (ROOT / "src/dm_engine/schema.sql").read_bytes()
    assert hashlib.sha256(schema_bytes).hexdigest()
