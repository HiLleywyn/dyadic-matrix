# Commands and structured arguments

`run "literal command"` retains the existing shell-command behavior. Its source
is literal; variables are never interpolated into shell code.

Use `exec` when a fixed program needs data from inputs or previous steps:

```dm
matrix "inspect-data" {
    input payload
    on "local" {
        exec "python3" {
            args ["-c", "import sys; print(sys.argv[2])", "--", $payload]
        }
        save outputs as observed
    }
}
```

The example requires a separately installed `python3`. Choose its actual local
name/path in both source and policy; the bundled `dm` runtime is not a general
Python interpreter. [argv.dm](../examples/argv.dm) and its
[policy](../examples/argv-policy.json) form a complete pair.

The executable is literal, and `args` is an explicit array of up to 64 arguments.
Every argument evaluates to text, at most 4,096 Unicode code points. The entire
vector, including the program, is bounded to 16 KiB of UTF-8 JSON. NUL, invalid
UTF-8 and Windows batch programs (`.cmd`/`.bat`) are refused. Data arguments must
follow a literal `--`; the program and option prefix stay fixed in source.
Dynamic `cmd.exe` arguments are refused. PowerShell data requires a literal
`-File` script after optional `-NoLogo`, `-NoProfile`, `-NonInteractive` flags;
dynamic command/encoded-command modes are refused.

The worker evaluates and freezes the vector before dispatch. Its hash is retained
with the effect receipt; restarts and safe retries reuse the frozen vector.
Inputs do not become shell text. The target program still interprets its own
arguments: `--` has the meaning that program implements. Review the fixed
program, script and options. This is process parameterization, not an OS sandbox,
and does not make an unsafe program or deliberately evaluating script safe.

## Local permission

The local policy grants the exact program and fixed prefix independently from
shell commands:

```json
{
  "format": 1,
  "root": ".",
  "commands": [],
  "executables": [{
    "program": "python3",
    "prefix": ["-c", "import sys; print(sys.argv[2])", "--"]
  }],
  "max_seconds": 30
}
```

`deny_executables` uses the same exact program/prefix pairs and wins over an
identical allow grant. These are exact pairs, not wildcard or prefix-pattern
rules. Changing policy or source requires review again. A shell-command grant
does not grant `exec`. The local adapter calls the process API directly.

## Hosted transport

Dyadic uses a separate `exec` Runner job with `argv-v1` and `control-v1`
negotiation. Unaware Runners cannot claim it. Its pickup payload contains an
argument vector, not a fallback shell command. The existing reviewed computer,
account/project scope, cancellation, bounded output and process-tree controls
still apply. A platform must ship that adapter before it can advertise hosted
support; a standalone package does not update a paired Runner.

See [retry rules](failure-handling.md) and
[Dyadic Developers](https://dyadic.app/developers/matrix/).
