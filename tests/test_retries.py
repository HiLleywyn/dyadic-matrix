"""Retries need trusted adapter evidence, retained deadlines and bounded work."""
from datetime import datetime,timedelta,timezone
import json
import pytest
from dm_engine.durable import Matrices,decoded,digest
from dm_engine.errors import Invalid
from dm_engine.language import compile_source,review_subject
from dm_engine.local import LocalHost
from test_local import fixture,start


SOURCE='''matrix "retry-fixture" {
 budget steps 10
 retry 2 backoff 2s
 on "local" { run "literal" }
}'''


async def setup(db,source=SOURCE):
    async def authorize(conn,run):return run['user_id']==42
    store=Matrices(db,authorize=authorize)
    graph=compile_source(source)
    definition=await store.register(42,source,{},digest(review_subject(graph,{})))
    return store,await store.start(42,definition['id'],'retry-fixture')


class Ports:
    def __init__(self,basis='pre_effect',state='failed',key=True):
        self.basis,self.state,self.key=basis,state,key;self.requests=[];self.attempts=[]
    async def start(self,conn,run,row,values):
        self.requests.append(str(row['request_id']))
        self.attempts.append(decoded(row['receipt'])['_matrix_retry']['attempt_id'])
        authority={'basis':self.basis,'key':str(row['request_id']) if self.key else 'wrong','contract':'fixture-idempotency'}
        return {'state':self.state,'output':{'reason':'Controlled adapter fixture'},'receipt':{'dispatch':'fixture','pre_effect_failure':True,'retry_safe':authority}}
    async def reconcile(self,*args):raise AssertionError('Backoff is owned by the engine, not adapter polling')


async def test_backoff_restart_exhaustion_and_attempt_identity_are_durable(db):
    store,run=await setup(db);ports=Ports();clock=datetime.now(timezone.utc)
    await store.advance(run['id'],ports,now=clock)
    first=(await store.inspect(42,run['id']))['steps'][0]
    assert first['state']=='waiting' and first['wake_at']==clock+timedelta(seconds=2)
    store=Matrices(db,authorize=store.authorize)
    await store.advance(run['id'],ports,now=first['wake_at']-timedelta(microseconds=1))
    assert len(ports.requests)==1
    await store.advance(run['id'],ports,now=first['wake_at'])
    second=(await store.inspect(42,run['id']))['steps'][0]
    assert second['wake_at']==first['wake_at']+timedelta(seconds=4)
    await store.advance(run['id'],ports,now=second['wake_at'])
    record=await store.inspect(42,run['id']);meta=decoded(record['steps'][0]['receipt'])['_matrix_retry']
    assert record['run']['state']=='failed' and len(meta['history'])==3
    assert len(set(ports.requests))==1 and len(set(ports.attempts))==3
    assert all(item['state']=='failed' for item in meta['history']) and 'next_at' not in meta
    with pytest.raises(Invalid,match='has ended'):await store.control(42,run['id'],'resume')
    await store.advance(run['id'],ports,now=second['wake_at']+timedelta(days=1))
    assert len(ports.requests)==3


@pytest.mark.parametrize('basis,state,key,eligible',[
    ('untrusted','failed',True,False),('idempotent','failed',False,False),
    ('idempotent','failed',True,True),('pre_effect','unknown',True,False)])
async def test_retry_requires_a_known_failure_and_matching_adapter_contract(db,basis,state,key,eligible):
    store,run=await setup(db);ports=Ports(basis,state,key)
    await store.advance(run['id'],ports)
    record=await store.inspect(42,run['id']);row=record['steps'][0]
    assert row['state']==('waiting' if eligible else state)
    assert len(ports.requests)==1
    if state=='unknown':assert record['run']['state']=='attention'


async def test_effect_output_cannot_grant_retry_authority(db):
    store,run=await setup(db)
    class UntrustedOutput:
        async def start(self,*args):
            return {'state':'failed','output':{'pre_effect_failure':True,'retry_safe':{'basis':'pre_effect'}}}
    await store.advance(run['id'],UntrustedOutput())
    assert (await store.inspect(42,run['id']))['run']['state']=='failed'


async def test_unserializable_effect_output_cannot_loop_or_gain_retry_authority(db):
    store,run=await setup(db)
    cyclic=[];cyclic.append(cyclic)
    class BrokenOutput:
        async def start(self,*args):
            return {'state':'completed','output':cyclic,'receipt':{'pre_effect_failure':True,'retry_safe':{'basis':'pre_effect'}}}
    await store.advance(run['id'],BrokenOutput())
    record=await store.inspect(42,run['id']);row=record['steps'][0]
    assert record['run']['state']=='failed'
    assert decoded(row['output'])['output_sha256'] is None
    assert not decoded(row['receipt'])['_matrix_retry'].get('next_at')


@pytest.mark.parametrize('action',['cancel','revoke'])
async def test_cancel_or_revoked_authorization_during_backoff_prevents_another_dispatch(db,action):
    store,run=await setup(db);ports=Ports()
    await store.advance(run['id'],ports)
    row=(await store.inspect(42,run['id']))['steps'][0]
    if action=='cancel':await store.control(42,run['id'],'cancel')
    else:
        async def denied(conn,run):return False
        store.authorize=denied
    await store.advance(run['id'],ports,now=row['wake_at']+timedelta(seconds=1))
    assert len(ports.requests)==1


async def test_real_local_launch_failure_retries_once_without_repeating_a_process(db,tmp_path,monkeypatch):
    import asyncio
    path,source,_=fixture(tmp_path,"from pathlib import Path\np=Path('once.txt')\np.write_text(p.read_text()+'x' if p.exists() else 'x')")
    source=source.replace('on "local"','retry 2 backoff 1s\non "local"')
    host,run=await start(db,path,source)
    original=asyncio.create_subprocess_shell;launches=[]
    async def transient(*args,**kwargs):
        launches.append(True)
        if len(launches)==1:raise FileNotFoundError('Controlled pre-exec fixture')
        return await original(*args,**kwargs)
    monkeypatch.setattr(asyncio,'create_subprocess_shell',transient)
    await host.tick()
    row=(await host.store.inspect(host.actor,run['id']))['steps'][0]
    assert row['state']=='waiting' and not (tmp_path/'once.txt').exists()
    restarted=LocalHost(db,path)
    await restarted.store.advance(run['id'],restarted,now=row['wake_at'])
    await restarted.tick()
    record=await restarted.store.inspect(restarted.actor,run['id'])
    assert record['run']['state']=='completed' and (tmp_path/'once.txt').read_text()=='x'
    assert len(launches)==2
    assert [x['state'] for x in decoded(record['steps'][0]['receipt'])['_matrix_retry']['history']]==['failed','completed']


async def test_ancestor_budget_reserves_retry_work_before_admitting_children(db):
    source=SOURCE.replace('budget steps 10','budget steps 4')
    store,parent=await setup(db,source)
    child='matrix "retry-child" { print "inert" }';graph=compile_source(child)
    definition=await store.register(42,child,{},digest(review_subject(graph,{})))
    await store.start(42,definition['id'],'first-child',parent=parent['id'])
    with pytest.raises(Invalid,match='aggregate step budget'):
        await store.start(42,definition['id'],'second-child',parent=parent['id'])


@pytest.mark.parametrize('statement',['retry 6 backoff 1s','retry 1 backoff 0s','retry 1 backoff 61m','retry -1 backoff 1s','failure ignore'])
def test_invalid_failure_or_retry_policy_is_rejected(statement):
    with pytest.raises(Invalid):compile_source('matrix "bad" {\n'+statement+'\non "local" { run "literal" }\n}')


def test_plan_budget_includes_every_potential_attempt():
    with pytest.raises(Invalid,match='possible retry attempts'):
        compile_source(SOURCE.replace('budget steps 10','budget steps 2'))
    graph=compile_source(SOURCE.replace('budget steps 10','budget steps 3'))
    assert graph['steps'][0]['retry']=={'limit':2,'backoff_seconds':2}
