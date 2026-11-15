# Durable state and schema

The normative PostgreSQL DDL is [schema.sql](../src/dm_engine/schema.sql).
Its `workspace_matrix_` table prefix is a stable storage name; it does not
require the hosted Workspace or a Dyadic account table.

| Table | Responsibility |
|---|---|
| `workspace_matrices` | Exact source, derived plan, review, bindings and enabled triggers |
| `workspace_matrix_runs` | Immutable invocation snapshot, actor, ancestry, idempotency key and state |
| `workspace_matrix_steps` | Stable step/request identities, state, receipt, output, wait/lease deadlines and approval |
| `workspace_matrix_events` | Ordered actual cursor and step events |
| `workspace_matrix_triggers` | Account-scoped, payload-bound event deduplication |
| `workspace_matrix_invocations` | Durable pending/delivered/blocked trigger admissions |

Run states are `running`, `paused`, `attention`, `completed`, `failed`,
`cancelled`. Step states are `pending`, `dispatching`, `waiting`, `approval`,
`completed`, `skipped`, `failed`, `unknown`. An expired dispatch lease becomes
unknown. Reconciliation can resolve observed evidence but never manufactures a
successful receipt. Replay is a separate reviewed invocation with new effects.

Read and mutation queries bind the actor. Definitions and runs have composite
ownership constraints; child parent links retain that same actor. Ancestor
cycles and excessive depth are refused. The actor's admission lock makes
parallel start/idempotency and aggregate-child budget checks atomic.

Default hard bounds: 16 active runs, 200 definitions, 10,000 retained runs,
64 KiB retained step output, 16 triggers and eight child levels. Trigger admission
is limited to 1,000 queued invocations per UTC day and 1,000 pending items per
actor. Daily counts include delivered/blocked invocations. When scheduled work
cannot enter that queue, its due occurrence remains due for later coalesced
admission. Event admission rolls back on capacity failure, allowing explicit retry
with the same payload-bound event identity.

Ended run cursors and delivered/blocked trigger receipts expire after 90 days.
Active work and retained child ancestry are preserved. Event-ID deduplication is
bounded by retention. This is not an exactly-once claim about external services.

The database interface supplies `atomic()` yielding an async PostgreSQL connection
with `execute`, `fetchrow`, `fetch`, `fetchval`; its outer facade supplies
`execute`, `fetch_one`, `fetch_all`, `fetch_val`. JSON may arrive decoded or as
JSON text. Implementations must preserve transaction and advisory-lock semantics.
Never emulate these with a process-local lock in a multi-worker deployment.
