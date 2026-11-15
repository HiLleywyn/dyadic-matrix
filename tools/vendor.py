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
files = sorted((root / 'src/dm_engine').glob('*.py')) + [root / 'src/dm_engine/schema.sql', root / 'src/dm_engine/LICENSE']
manifest = {'source': 'https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693',
            'mirror': 'https://github.com/HiLleywyn/dyadic-matrix', 'revision': None, 'files': {}}
if not args.dev:
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root): raise SystemExit('Commit the engine before vendoring its revision.')
    manifest['revision'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
for source in files:
    content = source.read_bytes();manifest['files'][source.name] = hashlib.sha256(content).hexdigest()
    destination = target / source.name
    if args.check:
        if not destination.is_file() or destination.read_bytes() != content: raise SystemExit('Vendored engine differs: ' + source.name)
    else:
        target.mkdir(parents=True, exist_ok=True);destination.write_bytes(content)
if not args.check:
    (target.parent / '__init__.py').write_text('"""Pinned external components, verified by their source manifests."""\n', encoding='utf-8', newline='\n')
    (target.parent / 'dm-engine.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
print('Verified' if args.check else 'Vendored', len(files), 'engine files')
