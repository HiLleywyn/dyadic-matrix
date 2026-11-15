import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import pytest
from dm_engine.durable import decoded, digest
from dm_engine.errors import Invalid
from dm_engine.local import LocalHost
from dm_engine.policy import Policy
from dm_engine.language import compile_source, review_subject


def fixture(tmp_path, program="print('local fixture')", seconds=5):
    script = tmp_path/'command.py';script.write_text(program, encoding='utf-8')
    argv = [sys.executable, str(script)]
    command = subprocess.list2cmdline(argv) if os.name == 'nt' else shlex.join(argv)
    path = tmp_path/'policy.json'
    path.write_text(json.dumps({'format':1,'root':str(tmp_path),'commands':[command],'max_seconds':seconds}), encoding='utf-8')
    source = 'matrix "local-fixture" {\non "local" { run ' + json.dumps(command) + ' }\n}'
    return path, source, command


async def start(db, path, source, key='once'):
    host = LocalHost(db, path);review = host.review(source)
    definition = await host.store.register(host.actor, source, review['bindings'], review['review_sha256'])
    return host, await host.store.start(host.actor, definition['id'], key)


def test_policy_is_explicit_exact_and_deny_takes_precedence(tmp_path):
    path, source, command = fixture(tmp_path)
    host = LocalHost(None, path);review = host.review(source)
    assert len(review['effects']) == 1
    value = json.loads(path.read_text());value['deny_commands']=[command];path.write_text(json.dumps(value))
    with pytest.raises(Invalid): host.review(source)
    value['deny_commands']=[];path.write_text(json.dumps(value))
    with pytest.raises(Invalid): host.review(source.replace('"local"','"somebody else"'))
    with pytest.raises(Invalid): host.review(source.replace('run ', 'cwd "../"\nrun '))
    with pytest.raises(Invalid): host.review('matrix "unsupported" { ask Iris "no implicit model" }')


async def test_real_local_process_restart_wait_exact_approval_and_no_duplicate_effect(db, tmp_path):
    path, source, command = fixture(tmp_path, "from pathlib import Path\np=Path('effect.txt')\np.write_text(p.read_text()+'x' if p.exists() else 'x')\nprint('observed')")
    source = source[:-1] + 'wait 60s\nrequire approval\nprint "finished"\n}'
    host, run = await start(db, path, source)
    await host.tick()
    record = await host.store.inspect(host.actor, run['id'])
    assert record['steps'][0]['state'] == 'completed'
    assert decoded(record['steps'][0]['output'])['output'].strip() == 'observed'
    assert (tmp_path/'effect.txt').read_text() == 'x'
    restarted = LocalHost(db, path)
    clock = datetime.now(timezone.utc) + timedelta(seconds=61)
    await restarted.store.advance(str(run['id']), restarted, now=clock)
    record = await restarted.store.inspect(host.actor, run['id'])
    approval = next(s for s in record['steps'] if s['state'] == 'approval')
    exact = digest({'run_id':str(run['id']),'step':approval['key'],'source_sha256':run['source_sha256'],'output':decoded(approval['output'])})
    await restarted.store.approve_step(host.actor, run['id'], approval['key'], exact)
    assert (await restarted.store.inspect(host.actor, run['id']))['run']['state'] == 'paused'
    await restarted.store.control(host.actor, run['id'], 'resume');await restarted.tick()
    assert (await restarted.store.inspect(host.actor, run['id']))['run']['state'] == 'completed'
    assert (tmp_path/'effect.txt').read_text() == 'x'


async def test_policy_revocation_after_queue_before_claim_prevents_the_process(db, tmp_path):
    path, source, _ = fixture(tmp_path, "from pathlib import Path\nPath('must-not-exist').write_text('bad')")
    host, run = await start(db, path, source)
    await host.store.advance(str(run['id']), host)
    value = json.loads(path.read_text());value['commands']=[];path.write_text(json.dumps(value))
    await host.tick()
    record = await host.store.inspect(host.actor, run['id'])
    assert record['run']['state'] == 'failed' and not (tmp_path/'must-not-exist').exists()


async def test_parallel_workers_do_not_dispatch_the_same_claim_twice(db, tmp_path):
    path, source, _ = fixture(tmp_path, "from pathlib import Path\np=Path('effect.txt')\np.write_text(p.read_text()+'x' if p.exists() else 'x')")
    host, run = await start(db, path, source)
    await asyncio.gather(host.tick(), LocalHost(db, path).tick())
    await host.tick()
    assert (await host.store.inspect(host.actor, run['id']))['run']['state'] == 'completed'
    assert (tmp_path/'effect.txt').read_text() == 'x'


async def test_lost_claim_expires_to_unknown_without_redispatch(db, tmp_path):
    path, source, _ = fixture(tmp_path, "raise AssertionError('never launched')")
    host, run = await start(db, path, source)
    await host.store.advance(str(run['id']), host)
    claimed = await host.claim();assert claimed is not None
    lease = await db.fetch_val('SELECT lease_until FROM workspace_matrix_steps WHERE run_id=$1', run['id'])
    restarted = LocalHost(db, path)
    await restarted.store.advance(str(run['id']), restarted, now=lease + timedelta(milliseconds=1))
    await restarted.tick()
    record = await host.store.inspect(host.actor, run['id'])
    assert record['run']['state'] == 'attention' and record['steps'][0]['state'] == 'unknown'
    assert decoded(record['steps'][0]['receipt'])['dispatch'] == 'local_claimed'


@pytest.mark.parametrize('cancel', [False, True])
async def test_timeout_or_explicit_cancel_joins_the_real_local_process(db, tmp_path, cancel):
    path, source, _ = fixture(tmp_path, 'import time\ntime.sleep(10)', seconds=1 if not cancel else 5)
    host, run = await start(db, path, source)
    work = asyncio.create_task(host.tick())
    if cancel:
        for _ in range(100):
            row = await db.fetch_one('SELECT receipt FROM workspace_matrix_steps WHERE run_id=$1', run['id'])
            if decoded(row['receipt']).get('pid'): break
            await asyncio.sleep(.02)
        else: raise AssertionError('Fixture process never reached its retained identity')
        await host.store.control(host.actor, run['id'], 'cancel')
    await asyncio.wait_for(work, timeout=8)
    record = await host.store.inspect(host.actor, run['id'])
    assert record['run']['state'] == ('cancelled' if cancel else 'failed')
    assert decoded(record['steps'][0]['output'])['termination'] == ('cancelled' if cancel else 'timeout')


async def test_real_cli_review_install_run_inspect_and_idempotent_request_key(db, tmp_path):
    path, source, _ = fixture(tmp_path, "from pathlib import Path\np=Path('effect.txt')\np.write_text(p.read_text()+'x' if p.exists() else 'x')")
    file = tmp_path/'workflow.dm';file.write_text(source, encoding='utf-8')
    env = {**os.environ, 'DM_DATABASE_URL':db.test_dsn, 'PYTHONPATH':str(Path(__file__).resolve().parents[1]/'src')}
    async def cli(*args, success=True):
        executable = [os.environ['DM_TEST_EXECUTABLE']] if os.environ.get('DM_TEST_EXECUTABLE') else [sys.executable, '-m', 'dm_engine']
        proc = await asyncio.create_subprocess_exec(*executable, *map(str,args), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, error = await asyncio.wait_for(proc.communicate(), timeout=20)
        assert proc.returncode == (0 if success else 2), error.decode()
        return json.loads(out) if out else None
    review = await cli('review', file, '--policy', path, '--json')
    await cli('install', file, '--policy', path, '--review', 'wrong', '--yes', success=False)
    assert not (tmp_path/'effect.txt').exists()
    definition = await cli('install', file, '--policy', path, '--review', review['review_sha256'], '--yes', '--json')
    first = await cli('run', definition['id'], '--policy', path, '--review', review['review_sha256'], '--request-key', 'cli-once', '--yes', '--json')
    assert first['run']['state'] == 'running' and not (tmp_path/'effect.txt').exists()
    await cli('worker', '--once', '--policy', path, '--json')
    again = await cli('run', definition['id'], '--policy', path, '--review', review['review_sha256'], '--request-key', 'cli-once', '--yes', '--json')
    assert first['run']['id'] == again['run']['id']
    record = await cli('inspect', first['run']['id'], '--policy', path, '--json')
    assert record['run']['state'] == 'completed' and (tmp_path/'effect.txt').read_text() == 'x'


@pytest.mark.parametrize('db', [False], indirect=True)
async def test_cli_initializes_its_empty_database_with_the_bundled_schema(db):
    executable = [os.environ['DM_TEST_EXECUTABLE']] if os.environ.get('DM_TEST_EXECUTABLE') else [sys.executable, '-m', 'dm_engine']
    env = {**os.environ, 'DM_DATABASE_URL': db.test_dsn}
    process = await asyncio.create_subprocess_exec(*executable, 'init-db', '--yes', env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, error = await asyncio.wait_for(process.communicate(), timeout=20)
    assert process.returncode == 0, error.decode()
    assert b'Initialized dm schema.' in out
    assert await db.fetch_one('SELECT count(*) AS n FROM workspace_matrices') == {'n': 0}


@pytest.mark.parametrize('handling',['continue','stop'])
async def test_known_failure_fallback_is_explicit_and_retains_original_outcome(db,tmp_path,handling):
    source=(Path(__file__).resolve().parents[1]/'examples/fallback.dm').read_text().replace('failure continue','failure '+handling)
    path=tmp_path/'policy.json';path.write_text(json.dumps({'format':1,'root':'.','commands':['exit 7','echo fallback'],'max_seconds':5}))
    host,run=await start(db,path,source)
    await host.tick()
    record=await host.store.inspect(host.actor,run['id'])
    assert record['steps'][0]['state']=='failed'
    assert decoded(record['steps'][0]['output'])['exit_code']==7
    commands=[s for s in record['steps'] if decoded(s['spec'])['kind']=='command']
    if handling=='continue':
        assert record['run']['state']=='completed'
        observed=next(s for s in record['steps'] if decoded(s['spec']).get('variable')=='observed')
        assert decoded(observed['output'])['state']=='failed'
        assert decoded(observed['output'])['output']['exit_code']==7
        assert commands[1]['state']=='completed' and decoded(commands[1]['output'])['output'].strip()=='fallback'
    else:
        assert record['run']['state']=='failed'
        assert commands[1]['state']=='failed' and decoded(commands[1]['receipt'])['dependency_blocked']


async def test_unknown_outcome_cannot_flow_through_failure_continue_or_start_a_fallback(db):
    from dm_engine.durable import Matrices
    async def authorize(conn,run):return run['user_id']==42
    source='''matrix "unknown-handler" {
step observe {
 failure continue
 on "local" { run "first" }
 save outcome as observed
 on "local" { run "second" }
}
}'''
    graph=compile_source(source)
    review=review_subject(graph,{})
    store=Matrices(db,authorize=authorize)
    definition=await store.register(42,source,{},digest(review))
    run=await store.start(42,definition['id'],'unknown-handler')
    class Ports:
        resolved=False
        def __init__(self):self.started=[]
        async def start(self,conn,run,row,values):
            self.started.append(row['key'])
            return {'state':'unknown' if len(self.started)==1 else 'completed','output':{'reason':'Fixture outcome unavailable'},'receipt':{'dispatch':'fixture'}}
        async def reconcile(self,conn,run,row):
            return {'state':'completed','output':{'exit_code':0},'receipt':{'dispatch':'fixture','resolved':True}} if self.resolved else None
    ports=Ports();await store.advance(run['id'],ports)
    record=await store.inspect(42,run['id'])
    assert record['run']['state']=='attention' and len(ports.started)==1
    assert all(s['state']=='pending' for s in record['steps'][1:])
    await store.reconcile(42,run['id'],ports)
    assert len(ports.started)==1
    ports.resolved=True
    assert (await store.reconcile(42,run['id'],ports))['run']['state']=='paused'
    assert len(ports.started)==1
    await store.control(42,run['id'],'resume');await store.advance(run['id'],ports)
    assert (await store.inspect(42,run['id']))['run']['state']=='completed'
    assert len(ports.started)==2


async def test_revoking_policy_while_running_terminates_the_owned_process(db, tmp_path):
    path, source, _ = fixture(tmp_path, 'import time\ntime.sleep(10)', seconds=5)
    host, run = await start(db, path, source)
    work = asyncio.create_task(host.tick())
    for _ in range(100):
        row = await db.fetch_one('SELECT receipt FROM workspace_matrix_steps WHERE run_id=$1', run['id'])
        if decoded(row['receipt']).get('pid'): break
        await asyncio.sleep(.02)
    else: raise AssertionError('Fixture process was not admitted')
    value = json.loads(path.read_text());value['commands']=[];path.write_text(json.dumps(value))
    await asyncio.wait_for(work, timeout=5)
    record = await host.store.inspect(host.actor, run['id'])
    assert record['run']['state'] == 'failed' and decoded(record['steps'][0]['output'])['termination'] == 'policy_changed'


async def test_late_observed_result_reconciles_only_its_original_claim_and_requires_resume(db, tmp_path):
    path, source, _ = fixture(tmp_path, "import time\nfrom pathlib import Path\ntime.sleep(.5)\nPath('once.txt').write_text('once')", seconds=5)
    host, run = await start(db, path, source)
    work = asyncio.create_task(host.tick())
    for _ in range(100):
        row = await db.fetch_one('SELECT receipt,lease_until FROM workspace_matrix_steps WHERE run_id=$1', run['id'])
        if decoded(row['receipt']).get('pid'): break
        await asyncio.sleep(.01)
    else: raise AssertionError('Fixture process was not admitted')
    await host.store.advance(str(run['id']), host, now=row['lease_until'] + timedelta(milliseconds=1))
    assert (await host.store.inspect(host.actor, run['id']))['run']['state'] == 'attention'
    await work
    record = await host.store.inspect(host.actor, run['id'])
    assert record['steps'][0]['state'] == 'completed' and record['run']['state'] == 'attention'
    await host.store.control(host.actor, run['id'], 'resume');await host.tick()
    assert (await host.store.inspect(host.actor, run['id']))['run']['state'] == 'completed'
    assert (tmp_path/'once.txt').read_text() == 'once'
