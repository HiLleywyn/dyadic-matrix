# Local runner

The `dm` CLI runs the shared engine locally with PostgreSQL-backed state and an
explicit local command policy. The native Windows/Linux packages bundle the
engine's Python runtime and PostgreSQL driver; a separate Python installation is
not required for the CLI. Commands named in your workflow still require their
own programs to be installed. A dedicated PostgreSQL database is required for
durable execution; pure validation and expressions need no database.

## Database and credentials

Create a dedicated database using your existing PostgreSQL administration tools.
Set `DM_DATABASE_URL` in your local environment or service's protected credential
configuration. Keep credentials out of `.dm`, policy examples, command arguments,
screenshots and source control. The CLI never writes the connection string into
a definition, review or receipt. PostgreSQL's underlying authentication and
transport settings remain your responsibility.

Run `dm init-db --yes` once. Initialization creates the included engine tables
transactionally. It does not drop or replace existing tables, migrate somebody
else's schemas or start a workflow. Its table names are documented in
[state.md](state.md).

This host identifies its local actor from the OS user and assumes a private,
dedicated database. It is not an authenticated multi-tenant HTTP service. A
service using this engine must supply its own trusted identity and authorization
adapter.

## Policy

Copy [local-policy.json](../examples/local-policy.json) and choose its root and
exact command grants. Relative roots resolve against the policy file's directory,
not whichever working directory invoked the CLI. The policy permits a bounded
list of exact command strings, explicit denies and a 1–300 second timeout.
Explicit denies take precedence. Unknown fields, duplicate keys and invalid
types are refused. The formal shape is
[policy.schema.json](../schemas/policy.schema.json).

```json
{
  "format": 1,
  "root": ".",
  "commands": ["echo local-checkpoint"],
  "deny_commands": [],
  "max_seconds": 10
}
```

The policy is not an OS sandbox. Commands execute as your OS user through the
local shell. Source text and grants must be reviewed accordingly. The root bounds
the requested working directory; it cannot contain arbitrary code's filesystem
or network access. No source expression interpolates data into shell text.
Commands run without interactive stdin. The adapter's target is explicitly
`on "local"`, with the default profile.

## Review, install and admit

```sh
dm validate examples/local.dm
dm review examples/local.dm --policy examples/local-policy.json --json
dm install examples/local.dm --policy examples/local-policy.json --review REVIEW_SHA --yes
dm run local-checkpoint --policy examples/local-policy.json --review REVIEW_SHA --request-key checkpoint-1 --yes
```

Inspect the actual review output. `REVIEW_SHA` is its `review_sha256`, not a
hash of a filename or a prior source. It binds source, plan and resolved policy,
including the actual root. Installation starts nothing; triggers stay disabled
unless explicitly installed with `--enable`. A changed definition requires its
current `--revision` as well as fresh review.

`run` admits durable work and returns. It does not become the process executing
the command. Repeating the same request key and invocation returns the same run;
reusing it with different input/source fails. Supply declared JSON inputs with
`--input-file`.

## Worker and durable waits

```sh
dm worker --policy examples/local-policy.json --once
dm inspect RUN_ID --policy examples/local-policy.json --json
```

Run `worker` without `--once` under your usual service/process manager for
unattended progress. A worker advances due schedules and ready steps; it persists
wait deadlines and releases the tick. Closing a control/inspection client does
not remove or restart that work. If all workers are stopped, deadlines and
cursors remain in the database, and due work is admitted when a worker returns.
Database persistence is not a claim that execution proceeds without a running
host. Each local worker filters admission and execution to its OS actor.

Command admission first records a queued request. A separate transaction claims
that identity before starting the process. Restarting a worker cannot redispatch
a lost claim. A lease that expires without a result becomes unknown and requires
reconciliation. Policy and source/plan identity are checked again before launch;
policy changes during execution stop the owned foreground process. Cancellation
and timeout join that process and retain actual exit/output evidence. Output is
bounded, with explicit truncation metadata. A backgrounded descendant retaining
a pipe is recorded as unknown rather than hanging or claiming it ended.

## Approve, resume and control

Inspection returns exact approval subjects under `approvals`:

```sh
dm approve RUN_ID STEP --policy POLICY --review SUBJECT_SHA --yes
dm resume RUN_ID --policy POLICY --yes
dm worker --policy POLICY --once
dm pause RUN_ID --policy POLICY --yes
dm cancel RUN_ID --policy POLICY --yes
dm reconcile RUN_ID --policy POLICY --yes
```

Approval leaves the run paused. Resume permits a worker to continue; it does not
reuse a prior approval for a different subject or generated source. Pause stops
new dispatch and does not claim active effects stopped. Cancel requests local
process termination; receipts retain what was actually observed. An uncertain
outcome cannot be fixed by pressing resume or issuing a new command silently.
A late observed result can resolve its exact original claim while the run remains
in attention until explicit resume.

## Adapter coverage

The built-in local command host supports native data, branches, bounded iteration,
source-local function expansion, local commands, structured argument vectors,
known-failure branches, adapter-safe retries, waits, approvals and scheduling.
Remote models, file transfer, generated proposals and installed child-workflow
dispatch require an explicit host adapter. Unsupported effects are refused at
review; they are never rerouted to a paid account or another computer. Dyadic's
managed host supplies those adapters through its account, Runner, gateway,
storage and billing owners. Both hosts use the same language and durable engine.

See [policy.md](policy.md) for the adapter contract and
[Dyadic Developers](https://dyadic.app/developers/matrix/) for hosted execution.
