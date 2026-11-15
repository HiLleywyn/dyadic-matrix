"""Durable Matrix state over existing effect owners. A cursor never proves an effect.

Ports dispatch through authenticated server owners. A lost dispatch is unknown and
is never reissued. Waits are database deadlines; no worker sleeps for a workflow.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from .errors import Invalid, NotFound
from .language import compile_source, review_subject
from . import values as matrix_values

OUTPUT_BYTES = 65536
ACTIVE_RUNS = 16
MAX_DEFINITIONS = 200
MAX_RUNS = 10000
MAX_TRIGGER_INVOCATIONS = 1000


class MatrixBusy(Invalid):
    """Transient admission pressure; a trigger may wait without dispatching."""


def decoded(value):
    return json.loads(value) if isinstance(value, str) else value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str).encode('utf-8', errors='backslashreplace')).hexdigest()


def bounded(value, limit=OUTPUT_BYTES):
    try:
        text = json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)
        size = len(text.encode('utf-8'))
    except (UnicodeError, ValueError, TypeError): raise Invalid('Matrix data must be valid finite UTF-8 JSON.') from None
    if size > limit:
        raise Invalid('Matrix data exceeds its retained-output bound. Store a file and pass its exact reference instead.')
    return text


def now_at(value=None):
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc)


def next_trigger(triggers, after):
    from .timing import next_run
    dates = []
    for trigger in triggers:
        if trigger['kind'] == 'date':
            date = datetime.fromisoformat(trigger['at'])
            if date > after: dates.append(date)
        elif trigger['kind'] == 'schedule':
            day = trigger['every']
            cadence = {'every': 'day', 'time': trigger['time']} if day == 'day' else {
                'every': 'week', 'days': ['mon', 'tue', 'wed', 'thu', 'fri'] if day == 'weekday' else
                ['sat', 'sun'] if day == 'weekend' else [day], 'time': trigger['time']}
            dates.append(next_run(cadence, trigger['zone'], after))
        elif trigger['kind'] in ('interval', 'cron'):
            from .scheduling import next_at
            dates.append(next_at(trigger, after))
    return min(dates) if dates else None


class Matrices:
    def __init__(self, db, *, authorize, audit=None):
        self.db, self.audit, self.authorize = db, audit, authorize

    async def _event(self, conn, run, kind, *, step=None, **detail):
        await conn.execute('INSERT INTO workspace_matrix_events(run_id,user_id,kind,step,detail) VALUES($1::uuid,$2,$3,$4,$5::jsonb)',
                           str(run['id']), int(run['user_id']), kind, step, bounded(detail))
        if self.audit:
            await self.audit(conn, run, kind, step, detail)

    async def purge_expired(self):
        """Ninety-day ended cursors; never remove active work or its ancestry."""
        async with self.db.atomic() as conn:
            await conn.execute("DELETE FROM workspace_matrix_triggers WHERE created_at<now()-interval '90 days'")
            await conn.execute("DELETE FROM workspace_matrix_invocations WHERE state<>'pending' AND created_at<now()-interval '90 days'")
            await conn.execute("DELETE FROM workspace_matrix_runs r WHERE state IN ('completed','failed','cancelled') AND updated_at<now()-interval '90 days' "
                "AND NOT EXISTS (SELECT 1 FROM workspace_matrix_runs child WHERE child.parent_id=r.id)")

    async def register(self, user, source, bindings, review, *, expected_revision=None, enabled=None, _connection=None):
        graph = compile_source(source)
        if not isinstance(bindings, dict): raise Invalid('Resolve Matrix bindings before review.')
        identity = digest(review_subject(graph, bindings))
        if review != identity: raise Invalid('The source or resolved targets changed. Review this exact Matrix again.')
        bounded(bindings)
        async with (nullcontext(_connection) if _connection is not None else self.db.atomic()) as conn:
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'matrix-owner:' + str(int(user)))
            row = await conn.fetchrow('SELECT * FROM workspace_matrices WHERE user_id=$1 AND name=$2 FOR UPDATE', int(user), graph['name'])
            if row:
                if row['source_sha256'] == graph['source_sha256'] and row['review_sha256'] == identity:
                    if enabled is not None and bool(enabled) != row['enabled']:
                        return dict(await conn.fetchrow('UPDATE workspace_matrices SET enabled=$2,next_at=$3,updated_at=now() WHERE id=$1 RETURNING *',
                            row['id'], bool(enabled), next_trigger(graph['triggers'], now_at()) if enabled else None))
                    return dict(row)
                if expected_revision != row['revision']: raise Invalid('This Matrix changed. Review its current revision before replacing it.')
                ident, revision = str(row['id']), row['revision'] + 1
                await conn.execute('UPDATE workspace_matrices SET revision=$2,source=$3,source_sha256=$4,graph=$5::jsonb,bindings=$6::jsonb,'
                    'review_sha256=$7,triggers=$8::jsonb,enabled=$9,next_at=$10,updated_at=now() WHERE id=$1::uuid', ident, revision,
                    source, graph['source_sha256'], bounded(graph, 524288), bounded(bindings), identity, bounded(graph['triggers']), bool(enabled),
                    next_trigger(graph['triggers'], now_at()) if enabled else None)
            else:
                if await conn.fetchval('SELECT count(*) FROM workspace_matrices WHERE user_id=$1', int(user)) >= MAX_DEFINITIONS:
                    raise Invalid('Remove an unused Matrix before adding another.')
                ident = str(uuid.uuid4())
                await conn.execute('INSERT INTO workspace_matrices(id,user_id,name,source,source_sha256,graph,bindings,review_sha256,triggers,enabled,next_at) '
                    'VALUES($1::uuid,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8,$9::jsonb,$10,$11)', ident, int(user), graph['name'], source,
                    graph['source_sha256'], bounded(graph, 524288), bounded(bindings), identity, bounded(graph['triggers']), bool(enabled),
                    next_trigger(graph['triggers'], now_at()) if enabled else None)
            if _connection is not None:
                return dict(await conn.fetchrow('SELECT * FROM workspace_matrices WHERE id=$1::uuid AND user_id=$2', ident, int(user)))
        return await self.definition(user, ident)

    async def definition(self, user, ident):
        row = await self.db.fetch_one('SELECT * FROM workspace_matrices WHERE user_id=$1 AND (id::text=$2 OR name=$2)', int(user), str(ident))
        if not row: raise NotFound(str(ident))
        return dict(row)

    async def start(self, user, ident, request_key, *, cause='manual', parent=None, inputs=None, replay=False, expected_review=None, _connection=None):
        if not isinstance(request_key, str) or not 1 <= len(request_key) <= 200: raise Invalid('Choose a bounded unique request key.')
        definition = await self.definition(user, ident)
        graph, bindings = decoded(definition['graph']), decoded(definition['bindings'])
        if inputs is not None and (not isinstance(inputs, dict) or len(inputs) > 16): raise Invalid('Matrix input is an object of at most 16 named values.')
        bounded(inputs or {})
        if any(key not in (inputs or {}) for key in graph.get('inputs', [])): raise Invalid('Supply the declared Matrix inputs.')
        fingerprint = digest({'matrix': str(definition['id']), 'review': definition['review_sha256'], 'inputs': inputs or {}, 'parent': parent, 'replay': replay})
        async with (nullcontext(_connection) if _connection is not None else self.db.atomic()) as conn:
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'matrix-owner:' + str(int(user)))
            current = await conn.fetchrow('SELECT * FROM workspace_matrices WHERE id=$1::uuid AND user_id=$2', definition['id'], int(user))
            if not current or current['review_sha256'] != (expected_review or definition['review_sha256']):
                raise Invalid('The reviewed Matrix changed before admission. Review it again.')
            old = await conn.fetchrow('SELECT * FROM workspace_matrix_runs WHERE user_id=$1 AND request_key=$2', int(user), request_key)
            if old:
                if old['request_sha256'] != fingerprint: raise Invalid('This request key is bound to a different Matrix invocation.')
                return dict(old)
            active = await conn.fetchval("SELECT count(*) FROM workspace_matrix_runs WHERE user_id=$1 AND state IN ('running','paused','attention')", int(user))
            if active >= ACTIVE_RUNS: raise MatrixBusy('This account has reached its active Matrix limit.')
            if await conn.fetchval('SELECT count(*) FROM workspace_matrix_runs WHERE user_id=$1', int(user)) >= MAX_RUNS: raise Invalid('Matrix history reached its retention limit.')
            depth = 0
            if parent:
                ancestor = await conn.fetchrow('SELECT depth FROM workspace_matrix_runs WHERE id=$1::uuid AND user_id=$2', str(parent), int(user))
                if not ancestor or ancestor['depth'] >= 8: raise Invalid('The child Matrix depth limit was reached.')
                cycle = await conn.fetchval('WITH RECURSIVE ancestors AS (SELECT id,parent_id,matrix_id FROM workspace_matrix_runs WHERE id=$1::uuid AND user_id=$2 '
                    'UNION ALL SELECT r.id,r.parent_id,r.matrix_id FROM workspace_matrix_runs r JOIN ancestors a ON r.id=a.parent_id WHERE r.user_id=$2) '
                    'SELECT count(*) FROM ancestors WHERE matrix_id=$3::uuid', str(parent), int(user), str(definition['id']))
                if cycle: raise Invalid('A Matrix cannot recursively invoke an ancestor Matrix.')
                depth = ancestor['depth'] + 1
                # Every reviewed ancestor owns an aggregate, lifetime expansion budget.
                # Completed/cancelled child attempts still consume it. The owner
                # admission lock above makes sibling admission atomic.
                ancestors = await conn.fetch('WITH RECURSIVE parents AS (SELECT id,parent_id,graph FROM workspace_matrix_runs WHERE id=$1::uuid AND user_id=$2 '
                    'UNION ALL SELECT r.id,r.parent_id,r.graph FROM workspace_matrix_runs r JOIN parents p ON r.id=p.parent_id WHERE r.user_id=$2) SELECT id,graph FROM parents', str(parent), int(user))
                for ancestor in ancestors:
                    parent_graph = decoded(ancestor['graph'])
                    if 'budgets' not in parent_graph: continue
                    consumed = await conn.fetchval('WITH RECURSIVE children AS (SELECT id,graph FROM workspace_matrix_runs WHERE id=$1::uuid AND user_id=$2 '
                        'UNION ALL SELECT r.id,r.graph FROM workspace_matrix_runs r JOIN children c ON r.parent_id=c.id WHERE r.user_id=$2) '
                        "SELECT COALESCE(sum(jsonb_array_length(graph->'steps')),0) FROM children", ancestor['id'], int(user))
                    if consumed + len(graph['steps']) > parent_graph['budgets']['steps']:
                        raise Invalid('The ancestor Matrix aggregate step budget was reached; no child was admitted.')
            run = dict(await conn.fetchrow('INSERT INTO workspace_matrix_runs(id,user_id,matrix_id,parent_id,depth,source,source_sha256,review_sha256,graph,bindings,input,cause,request_key,request_sha256,state) '
                'VALUES($1::uuid,$2,$3::uuid,$4::uuid,$5,$6,$7,$8,$9::jsonb,$10::jsonb,$11::jsonb,$12,$13,$14,$15) RETURNING *',
                str(uuid.uuid4()), int(user), str(definition['id']), parent, depth, definition['source'], definition['source_sha256'], definition['review_sha256'],
                bounded(graph, 524288), bounded(bindings), bounded(inputs or {}), cause, request_key, fingerprint, 'attention' if replay else 'running'))
            for step in graph['steps']:
                await conn.execute('INSERT INTO workspace_matrix_steps(run_id,user_id,key,spec,request_id) VALUES($1::uuid,$2,$3,$4::jsonb,$5::uuid)',
                    str(run['id']), int(user), step['key'], bounded(step), str(uuid.uuid5(run['id'], step['key'])))
            await self._event(conn, run, 'created', source_sha256=run['source_sha256'], review_sha256=run['review_sha256'], replay_requires_review=replay, parent_id=parent)
        return run

    async def inspect(self, user, ident, after=0):
        row = await self.db.fetch_one('SELECT * FROM workspace_matrix_runs WHERE id::text=$1 AND user_id=$2', str(ident), int(user))
        if not row: raise NotFound(str(ident))
        steps = await self.db.fetch_all('SELECT * FROM workspace_matrix_steps WHERE run_id=$1::uuid AND user_id=$2', str(ident), int(user))
        order = {node['key']: i for i, node in enumerate(decoded(row['graph'])['steps'])}
        steps.sort(key=lambda step: order[step['key']])
        events = await self.db.fetch_all('SELECT * FROM workspace_matrix_events WHERE run_id=$1::uuid AND user_id=$2 AND id>$3 ORDER BY id LIMIT 500', str(ident), int(user), int(after))
        return {'run': dict(row), 'steps': [{k: v for k, v in dict(s).items() if k != 'dispatch_input'} for s in steps], 'events': [dict(e) for e in events], 'event_limit': 500}

    async def control(self, user, ident, action):
        if action not in ('pause', 'resume', 'cancel'): raise Invalid('Choose pause, resume or cancel.')
        async with self.db.atomic() as conn:
            row = await conn.fetchrow('SELECT * FROM workspace_matrix_runs WHERE id::text=$1 AND user_id=$2 FOR UPDATE', str(ident), int(user))
            if not row: raise NotFound(str(ident))
            if row['state'] in ('completed', 'failed', 'cancelled'): raise Invalid('This Matrix has ended. Replaying it creates separate work requiring review.')
            if action == 'resume' and await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state IN ('dispatching','unknown','approval')", row['id']):
                raise Invalid('Reconcile uncertain steps or approve the exact waiting step before resuming.')
            state = {'pause': 'paused', 'resume': 'running', 'cancel': 'cancelled'}[action]
            await conn.execute('UPDATE workspace_matrix_runs SET state=$2,updated_at=now() WHERE id=$1', row['id'], state)
            await self._event(conn, row, action, active_effects='May still be running; cancellation receipts are separate.')
        return await self.inspect(user, ident)

    async def approve_step(self, user, ident, key, expected, *, _connection=None):
        async with (nullcontext(_connection) if _connection is not None else self.db.atomic()) as conn:
            run = await conn.fetchrow('SELECT * FROM workspace_matrix_runs WHERE id::text=$1 AND user_id=$2 FOR UPDATE', str(ident), int(user))
            if not run: raise NotFound(str(ident))
            row = await conn.fetchrow('SELECT * FROM workspace_matrix_steps WHERE run_id=$1 AND key=$2 FOR UPDATE', run['id'], key)
            if not row or row['state'] != 'approval': raise Invalid('This step is not waiting for approval.')
            exact = digest({'run_id': str(run['id']), 'step': key, 'source_sha256': run['source_sha256'], 'output': decoded(row['output'])})
            if expected != exact: raise Invalid('The approval subject changed. Inspect and review the exact waiting step.')
            repeat = decoded(row['spec'])['kind'] == 'child'
            await conn.execute("UPDATE workspace_matrix_steps SET approved_sha256=$3,state=$4,finished_at=CASE WHEN $5 THEN now() ELSE NULL END WHERE run_id=$1 AND key=$2", run['id'], key, exact, 'pending' if repeat else 'completed', not repeat)
            await conn.execute("UPDATE workspace_matrix_runs SET state='paused',updated_at=now() WHERE id=$1", run['id'])
            await self._event(conn, run, 'approved', step=key, approval_sha256=exact)
        if _connection is None:
            return await self.inspect(user, ident)

    async def reconcile(self, user, ident, ports):
        async with self.db.atomic() as conn:
            run = await conn.fetchrow('SELECT * FROM workspace_matrix_runs WHERE id::text=$1 AND user_id=$2 FOR UPDATE', str(ident), int(user))
            if not run: raise NotFound(str(ident))
            if run['state'] not in ('attention', 'paused'): raise Invalid('Reconcile a paused run or one needing attention.')
            steps = await conn.fetch("SELECT * FROM workspace_matrix_steps WHERE run_id=$1 AND state='unknown' FOR UPDATE", run['id'])
            for step in steps:
                if not decoded(step['receipt']): continue
                result = await ports.reconcile(conn, dict(run), dict(step))
                if result and result['state'] != 'unknown': await self._finish(conn, dict(run), dict(step), result['state'], result.get('output'), result.get('receipt'))
            unknown = await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state IN ('unknown','approval')", run['id'])
            if not unknown: await conn.execute("UPDATE workspace_matrix_runs SET state='paused',updated_at=now() WHERE id=$1", run['id'])
            await self._event(conn, dict(run), 'reconciled', unresolved=unknown, execution_replayed=False)
        return await self.inspect(user, ident)

    async def _trigger_capacity(self, conn, user, clock, *, nonblocking=False):
        key = 'matrix-trigger:' + str(int(user))
        if nonblocking:
            if not await conn.fetchval('SELECT pg_try_advisory_xact_lock(hashtextextended($1,0))', key): return None
        else: await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', key)
        midnight = clock.replace(hour=0, minute=0, second=0, microsecond=0)
        daily = await conn.fetchval('SELECT count(*) FROM workspace_matrix_invocations WHERE user_id=$1 AND created_at>=$2', int(user), midnight)
        pending = await conn.fetchval("SELECT count(*) FROM workspace_matrix_invocations WHERE user_id=$1 AND state='pending'", int(user))
        return max(0, MAX_TRIGGER_INVOCATIONS - max(daily, pending))

    async def event(self, user, event_id, name, payload, *, kind='event'):
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200 or not isinstance(name, str) or not 1 <= len(name) <= 200:
            raise Invalid('Supply a bounded event ID and name.')
        if kind not in ('event', 'startup'): raise Invalid('Unknown Matrix event kind.')
        value = bounded(payload)
        async with self.db.atomic() as conn:
            await conn.execute('SELECT pg_advisory_xact_lock(hashtextextended($1,0))', 'matrix-event:' + str(int(user)))
            old = await conn.fetchrow('SELECT name,payload FROM workspace_matrix_triggers WHERE user_id=$1 AND event_id=$2', int(user), event_id)
            if old:
                if old['name'] != name or decoded(old['payload']) != payload: raise Invalid('This event ID is already bound to different data.')
                return {'accepted': True, 'duplicate': True}
            if await conn.fetchval("SELECT count(*) FROM workspace_matrix_triggers WHERE user_id=$1 AND created_at>now()-interval '1 day'", int(user)) >= 1000:
                raise Invalid('The daily Matrix event limit was reached.')
            if await conn.fetchval('SELECT count(*) FROM workspace_matrix_triggers WHERE user_id=$1', int(user)) >= 90000:
                raise Invalid('Matrix event retention is full. Wait for the retention pass before delivering more events.')
            await conn.execute('INSERT INTO workspace_matrix_triggers(user_id,event_id,name,payload) VALUES($1,$2,$3,$4::jsonb)', int(user), event_id, name, value)
            definitions = await conn.fetch('SELECT * FROM workspace_matrices WHERE user_id=$1 AND enabled', int(user))
            remaining = await self._trigger_capacity(conn, user, now_at())
            queued = 0
            for definition in definitions:
                if any(t['kind'] == kind and t['name'] == name for t in decoded(definition['triggers'])):
                    if queued >= remaining: raise MatrixBusy('The account Matrix trigger queue or daily invocation limit was reached; retry this event later.')
                    await conn.execute('INSERT INTO workspace_matrix_invocations(user_id,matrix_id,request_key,review_sha256,payload,cause) '
                        'VALUES($1,$2,$3,$4,$5::jsonb,$6) ON CONFLICT DO NOTHING', int(user), definition['id'], 'event:' + digest([event_id, str(definition['id'])]),
                        definition['review_sha256'], value, kind + ':' + name)
                    queued += 1
            return {'accepted': True, 'duplicate': False, 'queued': queued}

    async def tick(self, ports, *, now=None, actor=None):
        clock = now_at(now)
        async with self.db.atomic() as conn:
            definitions = await conn.fetch('SELECT * FROM workspace_matrices WHERE enabled AND next_at<=$1 AND ($2::bigint IS NULL OR user_id=$2) ORDER BY next_at FOR UPDATE SKIP LOCKED LIMIT 32', clock, actor)
            remaining = {}
            for definition in definitions:
                user = definition['user_id']
                if user not in remaining: remaining[user] = await self._trigger_capacity(conn, user, clock, nonblocking=True)
                if not remaining[user]: continue
                await conn.execute('INSERT INTO workspace_matrix_invocations(user_id,matrix_id,request_key,review_sha256,cause) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING',
                    definition['user_id'], definition['id'], 'schedule:' + str(definition['id']) + ':' + definition['next_at'].isoformat(), definition['review_sha256'], 'schedule')
                await conn.execute('UPDATE workspace_matrices SET next_at=$2 WHERE id=$1', definition['id'], next_trigger(decoded(definition['triggers']), clock))
                remaining[user] -= 1
        pending = await self.db.fetch_all("SELECT * FROM workspace_matrix_invocations WHERE state='pending' AND ($1::bigint IS NULL OR user_id=$1) ORDER BY checked_at,created_at LIMIT 32", actor)
        for item in pending:
            await self.db.execute('UPDATE workspace_matrix_invocations SET checked_at=now() WHERE user_id=$1 AND request_key=$2', item['user_id'], item['request_key'])
            definition = await self.definition(item['user_id'], str(item['matrix_id']))
            if not definition['enabled'] or definition['review_sha256'] != item['review_sha256']:
                await self.db.execute("UPDATE workspace_matrix_invocations SET state='blocked',reason='The reviewed source or trigger enablement changed.' WHERE user_id=$1 AND request_key=$2", item['user_id'], item['request_key']);continue
            try:
                await self.start(item['user_id'], str(item['matrix_id']), item['request_key'], cause=item['cause'], inputs={'event': decoded(item['payload'])}, expected_review=item['review_sha256'])
            except MatrixBusy:
                continue  # Admission stays bounded; no request was sent to an effect owner.
            except Invalid as exc:
                await self.db.execute("UPDATE workspace_matrix_invocations SET state='blocked',reason=$3 WHERE user_id=$1 AND request_key=$2", item['user_id'], item['request_key'], str(exc)[:400])
                continue
            await self.db.execute("UPDATE workspace_matrix_invocations SET state='delivered' WHERE user_id=$1 AND request_key=$2", item['user_id'], item['request_key'])
        active = await self.db.fetch_all("SELECT id FROM workspace_matrix_runs WHERE state='running' AND ($1::bigint IS NULL OR user_id=$1) ORDER BY updated_at LIMIT 64", actor)
        for run in active:
            await self.advance(str(run['id']), ports, now=clock)

    async def advance(self, ident, ports, *, now=None):
        """One bounded tick. Ports may only start/reconcile existing server-owned effects."""
        clock = now_at(now)
        async with self.db.atomic() as conn:
            raw = await conn.fetchrow("SELECT r.* FROM workspace_matrix_runs r WHERE r.id::text=$1 AND r.state='running' FOR UPDATE OF r SKIP LOCKED", str(ident))
            if not raw or not await self.authorize(conn, dict(raw)): return
            run = dict(raw)
            await conn.execute('UPDATE workspace_matrix_runs SET updated_at=$2 WHERE id=$1', run['id'], clock)
            rows = [dict(s) for s in await conn.fetch('SELECT * FROM workspace_matrix_steps WHERE run_id=$1 FOR UPDATE', run['id'])]
            state = {s['key']: s for s in rows}
            values = dict(decoded(run['input']))
            for s in rows:
                spec = decoded(s['spec'])
                if s['state'] == 'completed' and spec['kind'] in ('save', 'value'): values[spec['variable']] = decoded(s['output'])
            for row in rows:
                spec, status = decoded(row['spec']), row['state']
                if status in ('completed', 'skipped', 'failed', 'unknown', 'approval'): continue
                if status == 'dispatching':
                    if row['lease_until'] and row['lease_until'] <= clock:
                        await self._finish(conn, run, row, 'unknown', {'reason': 'Dispatch receipt unavailable. Reconcile; do not repeat.'})
                    continue
                if status == 'waiting':
                    if spec['kind'] == 'wait':
                        if row['wake_at'] <= clock: await self._finish(conn, run, row, 'completed', {'waited_until': row['wake_at'].isoformat()})
                    else:
                        result = await ports.reconcile(conn, run, row)
                        if result is not None: await self._finish(conn, run, row, result['state'], result.get('output'), result.get('receipt'))
                    continue
                parents = [state[k] for k in spec['after']]
                if any(p['state'] in ('failed', 'unknown') for p in parents):
                    await self._finish(conn, run, row, 'failed', {'reason': 'A dependency failed or has an uncertain outcome.'});continue
                if any(p['state'] not in ('completed', 'skipped') for p in parents): continue
                if spec.get('conditions'):
                    try:
                        if decoded(run['graph']).get('expression_version') != matrix_values.VERSION:
                            raise Invalid('The recorded Matrix expression version is unavailable; review an updated source separately.')
                        matched = True
                        for condition in spec['conditions']:
                            result = matrix_values.evaluate(condition, values)
                            if type(result) is not bool: raise Invalid('A Matrix condition must be a boolean.')
                            if not result: matched = False;break
                    except Invalid as exc:
                        await self._finish(conn, run, row, 'failed', {'reason': str(exc)});continue
                    if not matched:
                        await self._finish(conn, run, row, 'skipped', {'reason': 'Recorded condition did not match.'});continue
                condition = spec.get('condition')
                if condition:
                    value = values
                    for part in condition['path']:
                        if not isinstance(value, dict) or part not in value:
                            await self._finish(conn, run, row, 'unknown', {'reason': 'The condition value is unavailable.'});break
                        value = value[part]
                    else:
                        equal = value == condition['value']
                        if equal != (condition['operator'] == '=='):
                            await self._finish(conn, run, row, 'skipped', {'reason': 'Recorded condition did not match.'});continue
                    if row['state'] == 'unknown': continue
                if spec['kind'] == 'wait':
                    deadline = clock + timedelta(seconds=spec['seconds'])
                    await conn.execute("UPDATE workspace_matrix_steps SET state='waiting',wake_at=$3,started_at=$4,updated_at=now() WHERE run_id=$1 AND key=$2", run['id'], row['key'], deadline, clock)
                    row.update(state='waiting',wake_at=deadline)
                    await self._event(conn, run, 'wait', step=row['key'], wake_at=deadline.isoformat());continue
                if spec['kind'] == 'print': await self._finish(conn, run, row, 'completed', {'text': spec['text']});continue
                if spec['kind'] == 'value':
                    try:
                        if decoded(run['graph']).get('expression_version') != matrix_values.VERSION:
                            raise Invalid('The recorded Matrix expression version is unavailable; review an updated source separately.')
                        output = matrix_values.evaluate(spec['expression'], values)
                        if 'collection_limit' in spec and (type(output) is not list or len(output) > spec['collection_limit']):
                            raise Invalid('Foreach requires an array within its reviewed iteration limit; no items were dispatched.')
                    except Invalid as exc:
                        await self._finish(conn, run, row, 'failed', {'reason': str(exc)});continue
                    await self._finish(conn, run, row, 'completed', output, {'pure': True, 'expression_version': matrix_values.VERSION,
                        'input_sha256': digest(values), 'expression_sha256': digest(spec['expression'])})
                    if row['state'] == 'completed': values[spec['variable']] = output
                    continue
                if spec['kind'] == 'save':
                    outputs = [decoded(state[k]['output']) for k in spec['subjects']]
                    output = outputs[0] if len(outputs) == 1 else outputs
                    await self._finish(conn, run, row, 'completed', output);values[spec['variable']] = output;continue
                if spec['kind'] == 'approval':
                    subjects = [decoded(state[k]['output']) for k in spec['after']]
                    proposal = next((s for s in subjects if isinstance(s, dict) and s.get('proposal')), None)
                    await self._finish(conn, run, row, 'approval', {'input_sha256': digest({'values': values, 'subjects': subjects}),
                        **({'generated_file_id': proposal['file_id'], 'source_sha256': proposal['source_sha256']} if proposal else {})});continue
                # The adapter writes any dispatch identity before returning, inside
                # this transaction when its owner supports atomic admission.
                await self._event(conn, run, 'dispatch_requested', step=row['key'], request_id=str(row['request_id']), source_sha256=run['source_sha256'], step_kind=spec['kind'])
                try: result = await ports.start(conn, run, row, values)
                except (Invalid, NotFound): result = {'state': 'unknown', 'output': {'reason': 'A reviewed resource or capability is unavailable. Inspect it before resuming.'}}
                await self._finish(conn, run, row, result['state'], result.get('output'), result.get('receipt'))
            pending = await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state NOT IN ('completed','skipped')", run['id'])
            failed = await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state='failed'", run['id'])
            attention = await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state IN ('unknown','approval')", run['id'])
            active = await conn.fetchval("SELECT count(*) FROM workspace_matrix_steps WHERE run_id=$1 AND state IN ('dispatching','waiting')", run['id'])
            final = 'attention' if attention else 'failed' if failed and not active else 'completed' if not pending else 'running'
            if final != 'running':
                await conn.execute('UPDATE workspace_matrix_runs SET state=$2,updated_at=now() WHERE id=$1', run['id'], final)
                await self._event(conn, run, final)

    async def _finish(self, conn, run, row, state, output=None, receipt=None):
        try: encoded = bounded(output) if output is not None else None
        except Invalid:
            state, output = 'failed', {'reason': 'Output exceeded the Matrix retention bound. Inspect the retained effect receipt; dependent steps did not run.', 'output_sha256': digest(output)}
            encoded = bounded(output)
        ended = state in ('completed', 'skipped', 'failed')
        await conn.execute('UPDATE workspace_matrix_steps SET state=$3,output=$4::jsonb,receipt=$5::jsonb,started_at=COALESCE(started_at,now()),'
            'finished_at=CASE WHEN $6 THEN now() ELSE finished_at END,updated_at=now() WHERE run_id=$1 AND key=$2',
            run['id'], row['key'], state, encoded, bounded(receipt or decoded(row['receipt'])), ended)
        row.update(state=state,output=output,receipt=receipt or decoded(row['receipt']))
        await self._event(conn, run, 'step', step=row['key'], state=state, receipt=receipt or {}, output_sha256=digest(output) if output is not None else None)
