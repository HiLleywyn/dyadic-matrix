"""Copy the exact reviewed engine into Dyadic; CI verifies every vendored byte."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('dyadic', type=Path)
parser.add_argument('--check', action='store_true')
parser.add_argument('--dev', action='store_true')
args = parser.parse_args()
target = args.dyadic.resolve() / 'core/dyadic_core/_vendor/dm_engine'
assert (args.dyadic / 'core/pyproject.toml').is_file()
# The hosted app supplies its own adapter and migration owner. Vendor the actual
# shared interpreter/cursor, not a second local CLI or database initializer.
names = ('__init__.py', 'errors.py', 'language.py', 'values.py', 'commands.py', 'scheduling.py', 'timing.py', 'durable.py', 'LICENSE')
files = [root / 'src/dm_engine' / name for name in names]
schema_path = 'core/dyadic_core/migrations/0308_matrices.sql'
schema_hash = hashlib.sha256((root / 'src/dm_engine/schema.sql').read_bytes()).hexdigest()
if hashlib.sha256((args.dyadic / schema_path).read_bytes()).hexdigest() != schema_hash:
    raise SystemExit('The platform migration and portable schema differ; reconcile their explicit schema contracts first.')
manifest = {'source': 'https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693',
            'mirror': 'https://github.com/HiLleywyn/dyadic-matrix', 'revision': None,
            'platform_schema': {'path': schema_path, 'sha256': schema_hash}, 'files': {}}
if not args.dev:
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root): raise SystemExit('Commit the engine before vendoring its revision.')
    manifest['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
previous_path = target.parent / 'dm-engine.json'
if not args.check and previous_path.is_file():
    previous = json.loads(previous_path.read_text(encoding='utf-8'))
    for name, expected in previous['files'].items():
        if name in names: continue
        old = (target / name).resolve()
        if not old.is_relative_to(target) or old.parent != target or not old.is_file():
            raise SystemExit('Unexpected stale vendor path; no files removed.')
        if hashlib.sha256(old.read_bytes()).hexdigest() != expected:
            raise SystemExit('A stale vendor file has local edits; preserve it before updating.')
    for name in set(previous['files']) - set(names): (target / name).unlink()
for source in files:
    content = source.read_bytes();manifest['files'][source.name] = hashlib.sha256(content).hexdigest()
    destination = target / source.name
    if args.check:
        if not destination.is_file() or destination.read_bytes() != content: raise SystemExit('Vendored engine differs: ' + source.name)
    else:
        target.mkdir(parents=True, exist_ok=True);destination.write_bytes(content)

dm_matrices = root / 'catalog' / 'matrices'
dyadic_matrices = args.dyadic.resolve() / 'catalog' / 'matrices'
matrix_count = 0
if dm_matrices.is_dir():
    for src in sorted(p for p in dm_matrices.rglob('*') if p.is_file()):
        rel = src.relative_to(dm_matrices)
        content = src.read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
        dst = dyadic_matrices / rel
        if args.check:
            if not dst.is_file() or dst.read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8') != content:
                raise SystemExit('Store matrix differs from dm: ' + rel.as_posix())
        else:
            dst.parent.mkdir(parents=True, exist_ok=True);dst.write_bytes(content)
        matrix_count += 1
if not args.check:
    (target.parent / '__init__.py').write_text('"""Pinned external components, verified by their source manifests."""\n', encoding='utf-8', newline='\n')
    (target.parent / 'dm-engine.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
print('Verified' if args.check else 'Vendored', len(files), 'engine files', f'and {matrix_count} store matrix files' if matrix_count else '')
