"""Literal programs receive bounded data arguments through exec, never a shell."""
import asyncio,json,sys
from pathlib import Path
import pytest
from dm_engine.durable import decoded,digest
from dm_engine.errors import Invalid
from dm_engine.language import compile_source
from dm_engine.local import LocalHost
from test_local import start


def fixture(tmp_path):
    prefix=['-c','import json,sys; print(json.dumps(sys.argv[1:]))','--']
    args=', '.join([*(json.dumps(v) for v in prefix),'$payload'])
    source='matrix "argv-fixture" {\ninput payload\non "local" {\nexec '+json.dumps(sys.executable)+' {\nargs ['+args+']\n}\n}\n}'
    path=tmp_path/'policy.json'
    path.write_text(json.dumps({'format':1,'root':'.','commands':[],
        'executables':[{'program':sys.executable,'prefix':prefix}],'max_seconds':5}),encoding='utf-8')
    return path,source


async def registered(db,path,source,payload):
    host=LocalHost(db,path);review=host.review(source)
    definition=await host.store.register(host.actor,source,review['bindings'],review['review_sha256'])
    return host,await host.store.start(host.actor,definition['id'],'argv-once',inputs={'payload':payload})


async def test_actual_argv_execution_preserves_shell_metacharacters_quotes_and_unicode(db,tmp_path,monkeypatch):
    path,source=fixture(tmp_path)
    payload='spaces; & $(touch NOT_CREATED) `echo nope` "quotes" \\ unicode \U0001f33f\nline'
    host,run=await registered(db,path,source,payload)
    async def forbidden_shell(*args,**kwargs):raise AssertionError('Exec must not launch a shell')
    monkeypatch.setattr(asyncio,'create_subprocess_shell',forbidden_shell)
    await host.tick()
    record=await host.store.inspect(host.actor,run['id']);row=record['steps'][0]
    assert record['run']['state']=='completed'
    assert json.loads(decoded(row['output'])['output'])==['--',payload]
    assert 'dispatch_input' not in row  # Transport inputs retain their existing privacy boundary.
    frozen=decoded(await db.fetch_val('SELECT dispatch_input FROM workspace_matrix_steps WHERE run_id=$1 AND key=$2',run['id'],row['key']))
    assert frozen['argv'][-1]==payload and frozen['sha256']==digest(frozen['argv'])
    assert decoded(row['receipt'])['argv_sha256']==frozen['sha256']
    assert not (tmp_path/'NOT_CREATED').exists()


async def test_worker_restart_uses_the_frozen_argument_vector(db,tmp_path):
    path,source=fixture(tmp_path);host,run=await registered(db,path,source,'original')
    await host.store.advance(run['id'],host)
    await db.execute('UPDATE workspace_matrix_runs SET input=$2::jsonb WHERE id=$1',run['id'],json.dumps({'payload':'changed fixture input'}))
    restarted=LocalHost(db,path);await restarted.tick()
    record=await restarted.store.inspect(restarted.actor,run['id'])
    assert record['run']['state']=='completed'
    assert json.loads(decoded(record['steps'][0]['output'])['output'])==['--','original']


async def test_tampered_frozen_arguments_cannot_be_launched(db,tmp_path):
    path,source=fixture(tmp_path);host,run=await registered(db,path,source,'original')
    await host.store.advance(run['id'],host)
    row=(await host.store.inspect(host.actor,run['id']))['steps'][0]
    frozen=decoded(await db.fetch_val('SELECT dispatch_input FROM workspace_matrix_steps WHERE run_id=$1 AND key=$2',run['id'],row['key']))
    frozen['argv'][-1]='changed without matching its retained digest'
    await db.execute('UPDATE workspace_matrix_steps SET dispatch_input=$3::jsonb WHERE run_id=$1 AND key=$2',run['id'],row['key'],json.dumps(frozen))
    await host.tick()
    record=await host.store.inspect(host.actor,run['id'])
    assert record['run']['state']=='failed'
    assert not decoded(record['steps'][0]['receipt']).get('pid')


@pytest.mark.parametrize('payload',[{},42,'x'*4097])
async def test_invalid_argument_data_fails_before_effect_dispatch(db,tmp_path,payload):
    path,source=fixture(tmp_path);host,run=await registered(db,path,source,payload)
    await host.tick()
    record=await host.store.inspect(host.actor,run['id'])
    assert record['run']['state']=='failed'
    assert decoded(record['steps'][0]['receipt'])=={'pre_effect_failure':True}


async def test_nul_data_is_rejected_at_admission_before_postgresql_or_dispatch(db,tmp_path):
    path,source=fixture(tmp_path)
    with pytest.raises(Invalid,match='NUL'):await registered(db,path,source,'bad\0argument')
    assert await db.fetch_val('SELECT count(*) FROM workspace_matrix_runs')==0


def test_exec_needs_its_own_program_prefix_grant_and_explicit_denies_win(tmp_path):
    path,source=fixture(tmp_path)
    host=LocalHost(None,path);host.review(source)
    policy=json.loads(path.read_text());policy['deny_executables']=policy['executables'];path.write_text(json.dumps(policy))
    with pytest.raises(Invalid,match='prefix'):host.review(source)
    policy.pop('deny_executables');policy['executables']=[];policy['commands']=[sys.executable];path.write_text(json.dumps(policy))
    with pytest.raises(Invalid,match='prefix'):host.review(source)


@pytest.mark.parametrize('argv',[[],[''],['x.cmd '],['x.bat.'],['exe',42],['exe','bad\0argument'],['exe','x'*4097],['exe',*['x'*4000]*5]])
def test_transport_rejects_invalid_or_oversize_vectors(argv):
    from dm_engine.commands import validate_vector
    with pytest.raises(Invalid):validate_vector(argv)


@pytest.mark.parametrize('statement',[
    'exec "program" { args [$payload] }',
    'exec "program" { args $payload }',
    'exec "program" { args [42] }',
    'exec "unsafe.cmd" { args ["--",$payload] }',
    'exec "cmd.exe" { args ["/c","echo","--",$payload] }',
    'exec "pwsh.exe" { args ["-Command","literal","--",$payload] }'])
def test_dynamic_programs_options_and_shell_command_modes_are_not_parameter_slots(statement):
    with pytest.raises(Invalid):compile_source('matrix "bad-argv" {\ninput payload\non "local" {\n'+statement+'\n}\n}')


def test_powershell_data_arguments_use_a_literal_script_file():
    graph=compile_source('matrix "file-argv" {\ninput payload\non "local" { exec "pwsh.exe" {\nargs ["-NoProfile","-File","reviewed.ps1","--",$payload]\n}\n}\n}')
    assert graph['steps'][0]['argument_prefix']==['-NoProfile','-File','reviewed.ps1','--']
