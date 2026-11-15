# Architecture and execution logic

The authored owner is exact UTF-8 source. Parsing is inert and returns a bounded
tree with Unicode ranges and a source hash. Compilation expands reachable
functions, imports, branches and iterations into a bounded dependency graph.
That graph includes the expression IR identity, import hashes, budgets and a
plan digest. An execution host resolves targets and records a review subject
covering source, plan and bindings.

`durable.Matrices` is the execution owner used by the hosted integration as well
as standalone hosts. It accepts a database, required async authorization
callback and optional audit callback. It never imports the Dyadic server,
account database, model provider or Runner implementation. Hosts provide effect
adapters with `start` and `reconcile` operations.

Each tick locks a run and its steps transactionally. Completed saved/pure values
are reconstructed from retained output. A pending step waits for its parents,
checks typed conditions, then records pure output, a wait deadline, an approval
subject or an effect dispatch receipt. Parent failures block dependent work.
Unknown external outcomes require reconciliation, not a fresh dispatch.

Wait deadlines and effect identities live in PostgreSQL. Concurrent ticks skip
locked runs. Invocation keys and database constraints deduplicate admission.
Step request UUIDs are derived from run and step identities. An adapter must
commit its dispatch identity before effects can begin outside that transaction.
The reference host contract explains how to claim queued work safely.

The optional audit callback observes actual engine events in the same
transaction. Dyadic uses it to connect Black Box provenance; another host may
use a different recorder. Audit metadata and successful step completion do not
establish external correctness or financial settlement.

## Source integration

Dyadic vendors the same package source and records upstream revision and file
hashes. Its small Workspace adapters translate existing error types, supply the
live-account authorization callback and retain existing API boundaries.
Target discovery, credentials, policy enforcement and billing stay with their
actual host owners. There is one compiler and one durable cursor implementation.

Run `python tools/vendor.py PATH_TO_DYADIC --check` to compare source bytes.
Normal synchronization requires a committed, clean engine checkout. `--dev`
marks a development copy without pretending it is pinned to a release commit.

## Open-core scope

The MIT engine includes parsing, compilation, pure data, deadline calculation,
state/schema and local tooling. Dyadic's managed control plane, tenant fleet and
gateway orchestration, enterprise policy management UI and hosted Black Box
service are separate commercial components. No platform credentials, customer
records or production infrastructure configuration are needed to inspect or
test this repository.
