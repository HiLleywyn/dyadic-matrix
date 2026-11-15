# Policy and effect-adapter contract

Compilation grants no authority. A host must authenticate its actor, resolve
owned targets and capabilities, calculate the complete review subject and obtain
the user's required review before installation/execution. The user identifier
passed to the engine is trusted host context, never identity inferred from
workflow text, model output or an event payload.

The review subject contains exact source SHA-256, plan SHA-256, expression IR
identity and resolved bindings. Any relevant source, target, capability,
credential-origin or policy change invalidates that review before a new effect.
Imported function bytes are hashed and frozen before this decision.

## Required checks

An adapter must enforce current actor/account, project/library, target and
credential ownership at the actual execution boundary. It must evaluate the
requested operation, exact arguments/resources, destination and delegation
context. A common tool name does not share permission. Denial and revocation
cannot be converted into an automatic grant by retrying, importing source or
using another adapter. Pure data cannot choose a new effect target or shell text.

`authorize(connection, run)` is required by the durable owner and is called
before a tick advances work. This is an additional live-host check, not a
replacement for the adapter's operation-specific policy. Hosts must enforce
authorization on their public read/control routes too.

## Dispatch and reconciliation

`start(connection, run, step, values)` returns an actual state, bounded output
and receipt. It must atomically retain a dispatch identity in the transaction
before a separate worker claims and begins external execution. Starting an
unrecorded subprocess inside an uncommitted transaction cannot satisfy this
contract. A crash between effect and recording must not cause blind replay.

`reconcile(connection, run, step)` consults the retained identity. It returns
observed completion, known failure, continued waiting or an unknown outcome.
An absent receipt, lost process, timeout or ambiguous HTTP result is not proof
that no effect happened. Commands returning nonzero can already have changed
the world. A paid model request may already have incurred charges.

If retries are supported by a host revision, they require an adapter-established
pre-effect failure or a real idempotency contract. A user-authored `safe` label,
model assertion or returned JSON cannot establish that safety. Current CLI help
and release notes define which retry facilities are actually implemented.

## Approvals, cancellation and evidence

Approval binds run ID, step key, source digest and exact retained subject.
Approving a parent cannot authorize generated child source. Approval leaves the
run paused; resume is a separate operation. Cancelling a cursor does not claim
an already dispatched command stopped. Hosts must join their real cancellation
owner and preserve termination/unknown receipts.

Retain useful per-operation evidence without secrets. Metadata, captured content,
encryption, retention and access are separate host decisions. The local/hosted
record should distinguish compiler validation, policy approval, effect admission,
adapter-observed output, completion and externally verified correctness.
