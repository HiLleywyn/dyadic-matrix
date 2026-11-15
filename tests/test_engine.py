import hashlib
from pathlib import Path
import pytest
from dm_engine import values
from dm_engine.cli import main
from dm_engine.durable import Matrices
from dm_engine.errors import Invalid
from dm_engine.language import compile_source, parse, review_subject
from dm_engine.scheduling import cron, interval, next_at
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('source', sorted((ROOT / 'examples').glob('*.dm')))
def test_every_example_compiles_without_a_host_or_effect(source):
    content = source.read_bytes()
    graph = compile_source(content.decode())
    assert graph['source_sha256'] == hashlib.sha256(content).hexdigest()
    assert graph['plan_sha256'] == compile_source(content.decode())['plan_sha256']
    assert len(graph['steps']) <= graph['budgets']['steps']


@pytest.mark.parametrize('source,expected', [('sum(map([1,2,3], $item * 2))', 12),
    ('filter([1,2,3], $item > 1)', [2,3]), ('not false and true', True),
    ('[true] == [1]', False), ('get(object(), "absent", 3)', 3)])
def test_pure_json_is_typed_deterministic_and_has_no_model_adapter(source, expected):
    assert values.evaluate(values.compile_expression(source), {}) == expected


@pytest.mark.parametrize('source', ['1 / 0', 'true + 1', '1 and true', '$missing.x',
    'open("file")', '__import__("os")', '1e999', 'min([])'])
def test_bad_data_or_host_execution_is_rejected(source):
    with pytest.raises(Invalid): values.evaluate(values.compile_expression(source), {})


def test_complete_language_is_default_with_nested_conditions_and_reviewed_plan():
    source = 'matrix "default" {\nlet count = 3\nif $count > 1 {\nif $count < 5 { print "yes" }\n}\n}'
    graph = compile_source(source)
    assert len(graph['steps'][-1]['conditions']) == 2
    assert review_subject(graph, {})['plan_sha256'] == graph['plan_sha256']
    assert parse(source)['range_unit'] == 'unicode_codepoints'


def test_bounded_expansion_and_required_host_authorization():
    with pytest.raises(Invalid): compile_source('matrix "x" { repeat 32 { repeat 32 { print "x" } } }')
    with pytest.raises(TypeError): Matrices(object())


def test_utc_intervals_cron_and_explicit_dst_fold_behavior():
    moment = datetime(2026,11,1,5,tzinfo=timezone.utc)
    assert next_at(interval('15m'), moment).isoformat() == '2026-11-01T05:15:00+00:00'
    trigger = cron('30 1 * * *', 'America/Chicago')
    first = next_at(trigger, moment)
    assert first.isoformat() == '2026-11-01T06:30:00+00:00'
    assert next_at(trigger, first).isoformat() == '2026-11-02T07:30:00+00:00'
    with pytest.raises(Invalid): cron('0 0 30 2 *')


def test_cli_validate_never_executes_and_invalid_input_has_a_failure_exit(capsys, tmp_path):
    assert main(['validate', str(ROOT/'examples/native-data.dm')]) == 0
    assert 'No effects dispatched' in capsys.readouterr().out
    invalid = tmp_path/'invalid.dm';invalid.write_text('matrix "x" { python "danger" }')
    assert main(['validate', str(invalid)]) == 2


def test_all_real_example_plans_and_local_policy_match_the_published_schemas():
    import json
    from jsonschema import Draft202012Validator
    plan = json.loads((ROOT/'schemas/plan.schema.json').read_text())
    policy = json.loads((ROOT/'schemas/policy.schema.json').read_text())
    Draft202012Validator.check_schema(plan);Draft202012Validator.check_schema(policy)
    for source in (ROOT/'examples').glob('*.dm'):
        Draft202012Validator(plan).validate(compile_source(source.read_bytes().decode()))
    for path in (ROOT/'examples').glob('*-policy.json'):
        Draft202012Validator(policy).validate(json.loads(path.read_text()))
