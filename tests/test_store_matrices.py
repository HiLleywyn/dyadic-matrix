"""Validate official Store Matrix templates in dm/catalog/matrices."""
from pathlib import Path
import json
import re

from dm_engine.language import compile_source

ROOT = Path(__file__).resolve().parents[1]
MATRICES_DIR = ROOT / "catalog" / "matrices"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
VER_RE = re.compile(r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")


def test_store_matrix_templates_compile_and_have_valid_manifests():
    folders = sorted(p for p in MATRICES_DIR.iterdir() if p.is_dir())
    assert len(folders) >= 13
    for folder in folders:
        manifest_path = folder / "matrix.json"
        source_path = folder / "matrix.dm"
        assert manifest_path.is_file(), folder.name
        assert source_path.is_file(), folder.name
        assert {p.name for p in folder.iterdir()} == {"matrix.json", "matrix.dm"}, folder.name
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["id"] == folder.name and ID_RE.fullmatch(folder.name)
        assert VER_RE.fullmatch(str(data["version"]))
        assert data["changes"] and data["changes"][0]["version"] == data["version"]
        source = source_path.read_text(encoding="utf-8")
        graph = compile_source(source)
        assert graph["name"] and graph["source_sha256"] and graph["steps"]
