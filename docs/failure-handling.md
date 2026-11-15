# Failure routing and durable retries

The default is `failure stop`. A failed step retains its failed state. Explicit
`failure continue` permits dependent work after a **known** failure. Like
`profile`, the directive applies to subsequent statements in that lexical block
and nested blocks. It does not change surrounding blocks.

`save outcome as name` retains the preceding step's state, output, logical
request ID and receipt. A parallel join produces an array of these envelopes.
Existing `save outputs` and `save response` still save raw output. An outcome
envelope cannot turn a nested file reference into file-read authority.

```dm
matrix "reviewed-fallback" {
    budget steps 30
    step primary {
        failure continue
        retry 2 backoff 2s
        on "local" { run "exit 7" }
        save outcome as observed
    }
    if $observed.state == "failed" {
        on "local" { run "echo fallback" }
    } else {
        print "No fallback needed."
    }
}
```

Both effects and the branch are reviewed. A nonzero exit is known failure; it
does not establish that an arbitrary command had no effects, and it does not
qualify for automatic retry. The explicit fallback can still run. A workflow
that handles a failure may complete while retaining that failed step.

Unknown outcomes block dependent work, including fallback and outcome projection.
Descendants remain pending. Reconcile the original dispatch identity; resolution
leaves the run paused and still requires explicit resume. A retry policy or
`failure continue` cannot bypass that boundary.

## Retry contract

`retry COUNT backoff DURATION` allows zero to five **additional** effect attempts.
The literal starting delay is one second to one hour, written in seconds/minutes.
Delays double, capped at one hour. `retry 0 backoff 1s` disables an inherited
policy. Native data steps, waits and approvals do not acquire effect retries.

A source directive is a limit, not proof that replay is safe. Only a trusted host
adapter can supply `receipt.retry_safe` for a known failed result:

- `{"basis":"pre_effect"}` also requires adapter-established
  `pre_effect_failure: true` before the effect executed.
- `{"basis":"idempotent","key":"LOGICAL_REQUEST_UUID","contract":"CONTRACT_ID"}`
  requires the retained logical request key and an actual supported idempotency
  contract. Inventing a contract label does not implement one.

Inputs, model answers, command output and native JSON values cannot provide this
authority. Unknown outcomes never enter automatic retry, even with an advertised
idempotency contract. Excess output after a completed effect does not authorize
retry either. Each host must document its supported contracts.

The local adapter classifies a `FileNotFoundError` reported by the subprocess
owner before command execution as pre-effect launch failure. Nonzero command
exits, timeout, cancellation, changed policy and lost results are not retry-safe.

## Persistence and budgets

Backoff is a retained UTC deadline, not a sleeping terminal process. The logical
request UUID stays stable; admitted attempts have distinct UUIDs. The reserved
`_matrix_retry` receipt field records attempt states, observation times, output
hashes and relevant adapter receipt identities. Adapter responses cannot replace
that internal counter. This does not promise retention of every earlier full
output; hosts may retain referenced jobs or recordings separately.

Review reserves maximum work: the step plus every permitted retry. Compilation
refuses a plan beyond `budget steps N`. Ancestor budgets reserve the same work
for children, including completed/cancelled children, under the owner admission
lock. Current authorization and adapter policy are checked again after backoff.
Cancellation or revocation prevents dispatch. An exhausted ended run cannot reset
its counter using Resume; replay is separate work with existing review/admission.

`dm inspect` exposes retry events and metadata with ordinary steps. Workflow
completion, adapter receipts and independent verification remain distinct.
