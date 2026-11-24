"""Shared Matrix engine conformance checks run identically in dm and Dyadic."""
import hashlib
import json
from pathlib import Path
from jsonschema import Draft202012Validator
import pytest

from dm_engine.errors import Invalid
from dm_engine.language import compile_source, parse
from dm_engine import values

ROOT = Path(__file__).resolve().parents[1]
VECTORS = json.loads((ROOT / "tests/conformance_vectors.json").read_text(encoding="utf-8"))
PLAN_SCHEMA = json.loads((ROOT / "schemas/plan.schema.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", VECTORS["programs"], ids=lambda c: c["id"])
def test_conformance_programs_compile_deterministically_against_schema(case):
    source = case["source"]
    tree = parse(source)
    graph = compile_source(source)
    assert tree["range_unit"] == "unicode_codepoints"
    assert graph["source_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()
    if case.get("source_sha256"):
        assert graph["source_sha256"] == case["source_sha256"]
    if case.get("plan_sha256"):
        assert graph["plan_sha256"] == case["plan_sha256"]
    assert [step["kind"] for step in graph["steps"]] == case["step_kinds"]
    Draft202012Validator(PLAN_SCHEMA).validate(graph)


@pytest.mark.parametrize("case", VECTORS["expressions"], ids=lambda c: c["expr"][:32])
def test_conformance_expressions_produce_exact_values(case):
    compiled = values.compile_expression(case["expr"])
    assert values.evaluate(compiled, case["inputs"]) == case["expected"]


@pytest.mark.parametrize("source", VECTORS["invalid_sources"])
def test_conformance_invalid_programs_are_rejected(source):
    with pytest.raises(Invalid):
        compile_source(source)


@pytest.mark.parametrize("expr", VECTORS["invalid_expressions"])
def test_conformance_invalid_expressions_are_rejected(expr):
    with pytest.raises(Invalid):
        values.evaluate(values.compile_expression(expr), {})
