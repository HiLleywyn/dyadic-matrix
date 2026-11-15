# Language reference

The entire alpha language is available by default. A document is UTF-8 `.dm`
source with one `matrix "identifier" { ... }` root. `version "1.0.0"` is
optional workflow metadata, not a language selector. Statements end at a newline
or closing brace. Strings use JSON double quotes and escaping. Comments start
with `#` or `//`. Source ranges use Unicode code points, not UTF-16 offsets.

## Statements

| Source | Meaning |
|---|---|
| `description "text"`, `version "text"` | Workflow metadata |
| `input name` | Require a named JSON invocation value |
| `step name { ... }` | Label a group of recorded steps |
| `gateway "name"`, `profile "name"`, `cwd "path"` | Explicit inherited execution selectors |
| `on "computer" { run "literal command" }` | Request an effect through a host adapter |
| `on "computer" { fetch "literal path" }` | Request file collection through its adapter |
| `parallel { step a { ... } step b { ... } }` | Independent branches, joined before the next statement |
| `save outputs as name`, `save response as name` | Retain preceding output under an immutable name |
| `copy name to "computer:/directory/"` | Explicit reviewed transfer; never infer file authority from JSON |
| `ask Iris "prompt containing $name"` | Host model adapter; availability and cost belong to that host |
| `ask Iris { prompt text }` | Preserve a multiline prompt as inert text |
| `wait 5m` | Persist a deadline; no process sleeps for the workflow |
| `print "text"` | Record literal text as a completed pure step |
| `require approval` | Persist exact-subject approval, followed by explicit resume |
| `run matrix "child.dm" { with name }` | Invoke a separately reviewed installed child |
| `generate matrix "proposal.dm"` | Retain an inert source proposal after a model response |

Scopes affect the derived reviewed graph. Reading source, opening a template or
compiling a graph executes nothing. The host resolves selectors and capabilities
before recording a review. Data cannot change a computer, credential, command or
permission. Shell strings remain literal even when they contain `$name`.

## Native expressions

`let total = sum(map($readings, $item.count * 2))` records deterministic data
processing. Values are JSON text, finite numbers, booleans, null, arrays and
objects. Use `$name`, `.property` and `[index]` for lookup. Bare declared names
are also accepted. No host attributes, filesystem, callbacks or evaluation of
Python/JavaScript are available.

Arithmetic: `+ - * / %`. Comparisons: `== != < <= > >=`.
Boolean logic: `not`, `and`, `or`. Parentheses control grouping. Multiplication
and division bind before addition; comparisons precede boolean logic.
Conditions require actual booleans; booleans are distinct from numbers. Missing
properties, invalid types, division by zero and non-finite/over-budget results
record failure. `and`, `or` and nested outer guards short-circuit.

| Function | Contract |
|---|---|
| `json(text)` | Parse bounded JSON |
| `text(value)` | Canonical JSON serialization, with sorted object keys |
| `get(object,key[,default])`, `has(object,key)` | Explicit optional-property handling; fallback is lazy |
| `length(value)` | Count text, array items or object keys |
| `keys(object)`, `values(object)` | Deterministic sorted-key order |
| `object([key,value],...)` | Build an object with unique text keys |
| `set(object,key,value)` | Return a copy with one property changed |
| `concat(array,...)`, `unique(array)` | Combine arrays or deduplicate canonical values |
| `sum(array)`, `min(array)`, `max(array)` | Numeric aggregation; min/max require a nonempty array |
| `map(array,expression)` | Transform each item |
| `filter(array,boolean)` | Retain matching items |
| `group(array,textKey)` | Group under text keys |
| `sort(array[,keyExpression])` | Stable ascending sort, all text or all numeric keys |

Collection expressions bind `$item` and `$index` lexically. Nested collections
have their own bindings. Functions do not mutate input. See
[native-data.dm](../examples/native-data.dm).

## Branches, iteration and budgets

```dm
if $healthy { print "ready" }
else { print "needs attention" }
repeat 3 { print "bounded repetition" }
foreach row in $rows limit 4 {
    let position = $index
    let count = $row.count
}
```

Repeat counts and foreach limits are literal integers from 1 to 32. Foreach
evaluates its array once and rejects excess length before any contained effect;
it never silently truncates. The compiler expands all possible slots into stable
steps. Unused slots are skipped. Each expansion records its source line, index
and limit. Local values are qualified per iteration and do not leak outside it.

`budget steps 100` sets the reviewed maximum expanded work, from 1 to the hard
ceiling of 512; the default is 60. Child work consumes every reviewed ancestor's
lifetime aggregate budget. Completed or cancelled child attempts still count.
Parallel groups contain at most eight branches. Source is at most 256 KiB,
256 statements and 12 nested blocks. Pure expressions have 8,192 characters,
256 nodes, depth 32, collections of 1,024 items, 64 KiB aggregate input/result
and a 20,000-unit processing meter. Numbers remain within ±(2^53−1).

## Reusable functions and frozen imports

```dm
function total {
    param rows
    let result = sum($rows)
}
call total { with rows = [1,2,3] }
save outputs as result
```

Functions have up to 16 explicit parameters, immutable locals and no ambient
caller-data capture. Calls expand into the same graph; they are not another
runtime. Recursion is rejected, and calls are bounded to eight levels.
The final body output can be retained with `save outputs as name`.

An import is a portable embedded function bundle:
`import util sha256 "LOWERCASE_SHA256" { ...functions... }`.
The digest covers the exact UTF-8 bytes between the import braces, including
whitespace. Its functions are called as `util.functionName`. The compiler
verifies the digest before review and records the bundle identity. Imports
cannot read mutable files, fetch a URL or execute initializers. Exporting the
`.dm` file preserves the complete frozen source.

## Failure handling and commands

`failure stop|continue`, `save outcome as name`, and `retry COUNT backoff DURATION`
provide explicit known-failure routing and bounded durable retries. Unknown
outcomes still require reconciliation. See the [failure contract](failure-handling.md).
`exec "literal-program" { args ["fixed", "--", $data] }` passes bounded text
arguments directly to a process with a separately reviewed program/prefix grant;
see [structured arguments](commands.md). These features are part of the default
alpha language and require no language-version declaration.

## Triggers

`trigger { interval 15m }` uses UTC epoch-aligned intervals, from one minute to
31 days. `cron "0 8 * * 1-5" zone "America/Chicago"` uses five numeric fields:
minute, hour, day of month, month and weekday. Sunday is 0 or 7. Numeric lists,
ascending ranges, wildcards and range steps are supported. There are no shell
commands, environment assignments or random fields in cron text.

When both day fields are restricted, either may match; a wildcard day field
uses the other field together with its own range/step match. Cron skips
nonexistent local times and chooses the first occurrence of a repeated local
time. Its search is bounded to eight years. Existing `schedule "08:00" every
"weekday" zone "America/Chicago"` shifts missing local times forward and uses
the first repeated time; this wall-clock treatment is explicit rather than
claimed identical to cron. `date`, named `event` and `startup` remain supported.

The durable queue deduplicates scheduled occurrence identities. Service downtime
coalesces missed periods into one due admission and calculates the next deadline
after now. It does not replay every missed minute. Account admission, pending
queue, history and spending limits still apply. See [state.md](state.md).

Full hosted usage: [Dyadic developer guide](https://dyadic.app/developers/matrix/).
