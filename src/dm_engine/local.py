"""Local host adapter: commit claims before shell execution; retain unknown outcomes.

The same durable.Matrices owner handles all graphs, waits, approvals and cursors.
This adapter owns only local command policy, process lifecycle and receipts.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import os
from pathlib import Path
import signal
import subprocess
import uuid
from .durable import Matrices, decoded, digest, bounded, OUTPUT_BYTES
from .errors import Invalid
from .language import compile_source, review_subject
from .policy import Policy


def actor_id():
    # A local installation uses its OS identity and private database. An HTTP
    # service must provide its own authenticated actor rather than reusing this.
    actor = str(os.getuid()) if hasattr(os, 'getuid') else getpass.getuser()
    return int.from_bytes(hashlib.sha256(actor.encode()).digest()[:8], 'big') % (2**63 - 1)


class LocalHost:
    def __init__(self, db, policy_path):
        self.db, self.policy_path, self.actor = db, Path(policy_path), actor_id()
        self.store = Matrices(db, authorize=self.authorize)

    async def authorize(self, conn, run): return run['user_id'] == self.actor

    def review(self, source, *, policy=None):
        graph = compile_source(source);policy = policy or Policy(self.policy_path)
        bindings, effects = policy.review(graph)
        return {'graph': graph, 'bindings': bindings, 'effects': effects,
                'review_sha256': digest(review_subject(graph, bindings)), 'source_sha256': graph['source_sha256']}

    def verify(self, run):
        policy = Policy(self.policy_path)
        current = self.review(run['source'], policy=policy)
        if current['review_sha256'] != run['review_sha256']:
            raise Invalid('The source, plan or local policy changed; review and install the current source before effects.')
        return policy

    def prepared(self,policy,row):
        spec=decoded(row['spec'])
        if spec['kind']=='command':return (*policy.command(spec),False)
        if spec['kind']=='exec':
            frozen=decoded(row['dispatch_input'])
            if not isinstance(frozen,dict) or 'argv' not in frozen or digest(frozen['argv'])!=frozen.get('sha256'):
                raise Invalid('The retained exec arguments are unavailable or changed.')
            return frozen['argv'],policy.argv_command(spec,frozen['argv']),True
        raise Invalid('No local adapter is configured for this effect.')

    async def start(self, conn, run, row, values):
        policy = self.verify(run);spec = decoded(row['spec'])
        self.prepared(policy,row)
        return {'state': 'waiting', 'receipt': {'dispatch': 'local_queued', 'request_id': str(row['request_id']),
                **({'argv_sha256':decoded(row['dispatch_input'])['sha256']} if spec['kind']=='exec' else {})}}

    async def reconcile(self, conn, run, row):
        # A queued claim may still be acquired. A lost process/result cannot be
        # reconstructed from a new command or its current output.
        receipt = decoded(row['receipt'])
        if receipt.get('dispatch') == 'local_queued': return None
        return {'state': 'unknown', 'receipt': receipt, 'output': {'reason': 'The retained local outcome is unavailable. No command was replayed.'}}

    async def tick(self):
        await self.store.tick(self, actor=self.actor)
        # Bounded drain: dependency progress can admit the next literal command,
        # but waits remain deadlines and release this worker invocation.
        for _ in range(64):
            claimed = await self.claim()
            if claimed is None: break
            run, row = claimed
            await self.execute(run, row)
            await self.store.advance(str(run['id']), self)

    async def claim(self):
        async with self.db.atomic() as conn:
            run = await conn.fetchrow("SELECT r.* FROM workspace_matrix_runs r WHERE r.user_id=$1 AND r.state='running' AND EXISTS "
                "(SELECT 1 FROM workspace_matrix_steps s WHERE s.run_id=r.id AND s.state='waiting' AND s.receipt->>'dispatch'='local_queued') "
                'ORDER BY r.created_at FOR UPDATE OF r SKIP LOCKED LIMIT 1', self.actor)
            if run is None: return None
            pending = await conn.fetchrow("SELECT * FROM workspace_matrix_steps WHERE run_id=$1 AND state='waiting' AND receipt->>'dispatch'='local_queued' ORDER BY key FOR UPDATE SKIP LOCKED LIMIT 1", run['id'])
            if pending is None: return None
            row = dict(pending)
            run = dict(run)
            try: policy = self.verify(run);self.prepared(policy,row)
            except (Invalid, OSError):
                await self.store._finish(conn, run, row, 'failed', {'reason': 'The reviewed local policy or working directory is unavailable. No process was started.'})
                return run, None
            receipt = {**decoded(row['receipt']), 'dispatch': 'local_claimed', 'claim_id': str(uuid.uuid4())}
            deadline = datetime.now(timezone.utc) + timedelta(seconds=policy.seconds + 10)
            await conn.execute("UPDATE workspace_matrix_steps SET state='dispatching',receipt=$3::jsonb,lease_until=$4 WHERE run_id=$1 AND key=$2", run['id'], row['key'], bounded(receipt), deadline)
            row.update(state='dispatching', receipt=receipt)
            return run, row

    async def execute(self, run, row):
        if row is None: return
        receipt = decoded(row['receipt']);process = None;reader = None;launch_requested = False
        chunks = [];size = 0;truncated = False
        try:
            policy = self.verify(run);command, cwd, direct = self.prepared(policy,row)
            if await self.db.fetch_val('SELECT state FROM workspace_matrix_runs WHERE id=$1 AND user_id=$2', run['id'], self.actor) != 'running':
                raise Invalid('The local run was paused or cancelled before process launch.')
            options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            launch_requested = True
            if direct:
                process = await asyncio.create_subprocess_exec(*command, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **options)
            else:
                process = await asyncio.create_subprocess_shell(command, cwd=cwd, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, **options)
            receipt.update(pid=process.pid)
            async def read():
                nonlocal size, truncated
                while chunk := await process.stdout.read(4096):
                    keep = chunk[:max(0, OUTPUT_BYTES - 2048 - size)]
                    if keep: chunks.append(keep);size += len(keep)
                    if len(keep) != len(chunk): truncated = True
            reader = asyncio.create_task(read())
            deadline = asyncio.get_running_loop().time() + policy.seconds;stopped = None
            waiter = asyncio.create_task(process.wait())
            await asyncio.wait_for(self.db.execute('UPDATE workspace_matrix_steps SET receipt=$3::jsonb WHERE run_id=$1 AND key=$2 AND request_id=$4', run['id'], row['key'], bounded(receipt), row['request_id']), timeout=min(5, policy.seconds))
            next_policy_check = asyncio.get_running_loop().time()
            while process.returncode is None:
                try: await asyncio.wait_for(asyncio.shield(waiter), timeout=0.25)
                except asyncio.TimeoutError: pass
                if process.returncode is not None: break
                state = await self.db.fetch_val('SELECT state FROM workspace_matrix_runs WHERE id=$1 AND user_id=$2', run['id'], self.actor)
                revoked = False
                if asyncio.get_running_loop().time() >= next_policy_check:
                    next_policy_check = asyncio.get_running_loop().time() + 1
                    try: revoked = Policy(self.policy_path).sha256 != policy.sha256
                    except (Invalid, OSError): revoked = True
                if state == 'cancelled' or revoked or asyncio.get_running_loop().time() >= deadline:
                    stopped = 'cancelled' if state == 'cancelled' else 'policy_changed' if revoked else 'timeout'
                    await self.stop(process);break
            try: await asyncio.wait_for(reader, timeout=1)
            except asyncio.TimeoutError:
                # A foreground shell can exit while an explicitly backgrounded
                # descendant retains its pipe. Do not hang or claim it ended.
                state, output = 'unknown', {'reason': 'A descendant retained the output stream after foreground exit. Inspect the local effect; it was not replayed.'}
                await self.record(run, row, state, output, receipt);return
            text = b''.join(chunks).decode('utf-8', errors='replace')
            encoded = text.encode('utf-8')
            if len(encoded) > OUTPUT_BYTES - 2048:
                truncated = True;text = encoded[:OUTPUT_BYTES - 2048].decode('utf-8', errors='ignore')
            output = {'exit_code': process.returncode, 'output': text,
                      'output_truncated': truncated, **({'termination': stopped} if stopped else {})}
            state = 'completed' if process.returncode == 0 and stopped is None else 'failed'
        except (Invalid, OSError) as exc:
            if process is None and launch_requested and isinstance(exc, FileNotFoundError):
                # The subprocess owner reports failure before executing the
                # reviewed command (for example, a vanished cwd or shell).
                # A nonzero command exit, timeout or lost receipt is different.
                state, output = 'failed', {'reason': 'The process could not be launched. No command was executed.'}
                receipt.update(pre_effect_failure=True,retry_safe={'basis':'pre_effect'})
            elif process is None and not launch_requested:
                state, output = 'failed', {'reason': 'Local policy, process launch or run admission failed before a process was started.'}
                receipt['pre_effect_failure'] = True
            else:
                if process is not None: await self.stop(process)
                state, output = 'unknown', {'reason': 'The local effect outcome is uncertain. Inspect the retained identity; no command was replayed.'}
        except BaseException:
            if process is not None: await self.stop(process)
            if reader is not None:
                reader.cancel();await asyncio.gather(reader, return_exceptions=True)
            # Leave the committed claim for lease expiry/reconciliation even if
            # this worker dies while recording its result.
            raise
        receipt['dispatch'] = 'local_ended'
        await self.record(run, row, state, output, receipt)

    async def record(self, run, row, state, output, receipt):
        async with self.db.atomic() as conn:
            active = await conn.fetchrow('SELECT * FROM workspace_matrix_steps WHERE run_id=$1 AND key=$2 AND user_id=$3 FOR UPDATE', run['id'], row['key'], self.actor)
            if active and active['state'] in ('dispatching', 'unknown') and active['request_id'] == row['request_id'] and decoded(active['receipt']).get('claim_id') == receipt.get('claim_id'):
                await self.store._finish(conn, run, dict(active), state, output, receipt)

    @staticmethod
    async def stop(process):
        if process.returncode is not None: return
        if os.name == 'nt':
            taskkill = str(Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/taskkill.exe')
            child = await asyncio.create_subprocess_exec(taskkill, '/PID', str(process.pid), '/T', '/F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            await child.wait()
        else:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
        await process.wait()
