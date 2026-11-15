# Development and verification

Install Python 3.12 or newer and `python -m pip install -e '.[test]'`.
Run `python -m pytest` for the standalone suite. Compile every source under
`examples/` with `dm validate`; evaluate data without granting external effects.
PostgreSQL tests require an explicitly supplied disposable test DSN and use
fixture-owned schemas. Never point them at production or an account database.

Change the authoritative engine here, then synchronize its exact reviewed files
into Dyadic with `tools/vendor.py`. A release records the engine commit and file
hashes. The hosted integration must pass its API, ownership, budget, cancellation,
restart, approval and recording tests against those same bytes. A copy that
merely looks similar is not a shared engine.

For language changes, update parser/compiler, pure IR, relevant execution state,
source examples, syntax vocabulary, schemas and docs together. Regenerate Store
templates and website examples from their authoritative sources. The alpha
language is updated as a whole; do not invent user-visible version opt-ins.

For effects, preserve explicit policy review, atomic dispatch identity, lost-
response reconciliation and real cancellation. Test the negative cases: missing
data, wrong types, over-budget work, changed imported bytes, incompatible targets,
cross-actor IDs, revoked capabilities and uncertain results.

Keep fixtures bounded and deterministic. No implicit model charges, production
commands, external sends or credential access belong in a test. Record runtime
and toolchain versions for native packaging. Build Windows and Linux separately,
test the installed commands and attach checksums/source provenance to releases.
GitHub is a secondary source mirror; its Actions are disabled for this project.

Contributions to project-authored code and docs use the repository MIT license.
Preserve third-party notices and identify upstream provenance when importing code.
