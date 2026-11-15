# Changelog

## 0.1.0-alpha.2

- `failure continue` and `save outcome` support reviewed fallback branches after
  known failures. Unknown outcomes still require reconciliation and resume.
- `retry COUNT backoff DURATION` retains bounded exponential deadlines, logical
  request identity and distinct attempt receipts. Only adapter-established safe
  pre-effect failures or implemented idempotency contracts qualify for retry.
- `exec` sends frozen, bounded text arguments to a literal program without shell
  interpolation. Local policies grant its exact program/prefix separately.
- Aggregate budgets reserve possible retry work, including nested workflows.
- Invalid database JSON, including NUL and cyclic effect output, fails before
  dependent work; output retention failure does not grant replay safety.

The complete alpha language remains the default. Package release numbers do not
introduce a language-version declaration or an opt-in syntax split.

## 0.1.0-alpha.1

Initial public parser, typed JSON expressions, expanded conditions/iteration,
frozen function imports, configurable budgets, interval/cron scheduling, shared
durable cursor and PostgreSQL local CLI. Native Windows/Linux packages include
the runtime, driver, schemas, documentation and third-party notices.
