# Dyadic Matrix (`dm`)

The `.dm` language and durable execution engine behind [Dyadic Matrix](https://dyadic.app/developers/matrix/).
MIT licensed, in alpha, with source that developers can inspect and run locally.
The complete alpha language is available by default.

A workflow describes reviewed work. Its source is data until an execution host
resolves capabilities, records the exact review and admits a run. Model output,
imported source and tool results cannot enlarge that grant. A recorded cursor
describes what the engine knows; it cannot prove an external effect happened.

## Source and documentation

- [Canonical source on lley.cat](https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693)
- [GitHub mirror](https://github.com/HiLleywyn/dyadic-matrix)
- [Dyadic developer guide](https://dyadic.app/developers/matrix/)
- [Language and syntax](docs/language.md)
- [Architecture and execution logic](docs/architecture.md)
- [Policy and adapter contract](docs/policy.md)
- [State and schema contract](docs/state.md)
- [Failure routing, fallback and retries](docs/failure-handling.md)
- [Structured command arguments](docs/commands.md)
- [Installation, packages and verification](docs/install.md)
- [Development and reproducibility](CONTRIBUTING.md)
- [Examples](examples/)

## Run source inspection locally

Python 3.12 or newer is sufficient for the parser, compiler and native JSON
operations. Portable IANA time-zone data is installed with the package. These
operations need no account,
API key, network access, model or hosted Dyadic service.

```sh
git clone https://github.com/HiLleywyn/dyadic-matrix.git
cd dyadic-matrix
python -m pip install .
dm --version
dm validate examples/native-data.dm
dm validate examples/iteration.dm --json
dm expr 'sum(map($readings, $item.count))' --input-file examples/readings.json
```

The lley.cat Git remote is
`https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693.git`.
Both remotes carry the same engine history. Versioned Windows and Linux
install packages, checksums and source revision manifests belong in Releases;
the release installer instructions distinguish an available package from a
verified installation. Builds run locally and in the existing build environment,
with no dependency on GitHub Actions.

## Run a local workflow

The local command host uses PostgreSQL for durable cursors, with a dedicated local
OS identity. Install `.[postgres]` from source, or use the bundled native package.
Create a dedicated database and set `DM_DATABASE_URL` using your normal protected
credential configuration. The engine never stores that connection string in a
workflow or review. See [the local runner guide](docs/local-runner.md).

```sh
dm init-db --yes
dm review examples/local.dm --policy examples/local-policy.json --json
# Inspect the source, plan, root directory and exact permitted command.
dm install examples/local.dm --policy examples/local-policy.json --review REVIEW_SHA --yes
dm run local-checkpoint --policy examples/local-policy.json --review REVIEW_SHA --request-key checkpoint-1 --yes
dm worker --policy examples/local-policy.json --once
```

Waits persist deadlines. A worker can be restarted later without rerunning
completed commands. `dm inspect RUN_ID --policy POLICY --json` exposes retained
steps and exact approval subjects. `dm approve RUN_ID STEP --review SUBJECT_SHA
--policy POLICY --yes` leaves the run paused; `dm resume` is separate. The local
policy grants exact command text and a root working directory, with explicit deny
precedence and a bounded timeout. The working directory is not an OS sandbox.

## A concrete workflow

```dm
matrix "reading-check" {
    input readings
    let good = filter($readings, $item.ok == true)
    let count = sum(map($good, $item.count))
    if $count > 0 {
        print "Observed readings need review"
    } else {
        print "No positive readings"
    }
    require approval
}
```

This is deterministic data processing. `filter`, `map` and `sum` call no model.
The approval is an actual persisted step, bound to its run, source and retained
subject. Approval leaves the run paused until explicit resume. Closing a client
does not own the run's lifetime.

## Why make execution explicit?

YAML and Python can implement these guarantees too. They are not inherently
unsafe. The comparison is between a naive orchestration loop and an engine that
makes these properties part of its contract:

| Concern | Naive loop or configuration | dm contract |
|---|---|---|
| Input becomes authority | Treat returned text as instructions | Inputs remain typed data; commands and targets are reviewed literals |
| Lost response | Retry because no response arrived | Reconcile recorded identity; unknown outcomes are not replayed |
| Shell interpolation | Construct shell text from untrusted values | Data expressions never interpolate shell code |
| Durable waits | Sleep in a terminal process | Persist a deadline and release the worker |
| Approval | A boolean in application memory | Exact subject digest, persisted decision and explicit resume |
| Branches and loops | Unrecorded dynamic fan-out | Bounded expansion with stable step and iteration identities |
| Reusable source | Load a mutable remote file during execution | Freeze imported function bytes and verify their digest before review |
| Data processing | Ask a model to parse or count JSON | Bounded, typed, deterministic native operations |
| Completion | Treat successful workflow exit as correctness | Retain actual receipts; completion alone proves no external correctness |

## What is in this repository?

`src/dm_engine/language.py` owns the inert lossless parser, source ranges,
dependency graph and reviewed expansion. `values.py` owns the bounded pure-data
IR. `scheduling.py` and `timing.py` calculate the next deadline. `durable.py`
owns transactional cursors, trigger deduplication, waits, approvals and effect
reconciliation over an explicit database/authorization/adapter contract.

The PostgreSQL schema is included. No Dyadic account table is required by the
standalone engine: a host must supply its authorization callback. External
commands, transfers and model calls use host adapters, which must satisfy the
[policy contract](docs/policy.md). A compiler result is not an authorization
decision. The local CLI executes explicitly granted commands on the local computer, using
these same durable cursors. Its built-in adapter supports native data, commands,
waits and approvals. Remote model requests, transfers and child dispatch require
a host adapter; the CLI refuses unsupported effects rather than rerouting them.

Dyadic vendors exact engine files and records the upstream revision and file
hashes. `tools/vendor.py` verifies that copy. The hosted integration provides
account authorization, owned target discovery, credentials, quotas, Runner and
model adapters, and Black Box recording. These are host responsibilities rather
than a second interpreter.

## The open-core boundary

This MIT repository contains the grammar/parser/compiler, native data processing,
execution state logic, local tooling, schema and policy evaluation contract.
The managed Dyadic control plane, multi-tenant fleet/gateway orchestration,
enterprise role/policy management UI and hosted Black Box service remain in
Dyadic. Using the language locally does not require purchasing that service.

## Verification and limits

Every executable source is bounded. The compiler rejects unknown operations,
undeclared references, cross-branch dependency mistakes, recursive functions,
changed import bytes and excessive expansion. Pure data has independent limits
for depth, collection size, bytes, numbers and aggregate work.

The engine does not promise exactly-once external effects, make a working
directory into a sandbox, or infer permission from an imported template.
Review [the state contract](docs/state.md) before implementing an adapter.
Fixtures, local execution, deployment and physical-device checks establish
different facts and are reported separately.

See [the MIT license](LICENSE) and [contributing guide](CONTRIBUTING.md).
