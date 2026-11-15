"""Build a native, portable release from an exact clean Git revision.

Run on the target OS. No network, repository writes or publication occur here.
Dependency installation is a separate, explicit build-environment step.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from dm_engine import __version__


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], text=True).strip()


def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def licenses(destination):
    destination.mkdir()
    names = ('asyncpg', 'tzdata', 'pyinstaller', 'pyinstaller-hooks-contrib',
             'altgraph', 'packaging', 'setuptools', 'pefile', 'pywin32-ctypes')
    included = {}
    for name in names:
        try: distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError: continue
        found = []
        for relative in distribution.files or ():
            if any(part.lower().startswith(('license', 'copying', 'notice')) for part in relative.parts):
                source = Path(distribution.locate_file(relative))
                if source.is_file():
                    target = destination / name / Path(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target);found.append(target.relative_to(destination).as_posix())
        if not found: raise RuntimeError('Missing license text for build dependency: ' + name)
        included[name] = {'version': distribution.version, 'notices': found}
    candidates = (Path(sys.base_prefix) / 'LICENSE.txt', Path(sys.base_prefix) / 'LICENSE',
                  Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt')
    python_license = next((p for p in candidates if p.is_file()), None)
    if python_license is None: raise RuntimeError('Cannot locate CPython license text')
    shutil.copyfile(python_license, destination / 'CPython-LICENSE.txt')
    return included


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if git('status', '--porcelain', '--untracked-files=normal'):
        raise SystemExit('Release builds require a clean committed source tree.')
    machine = platform.machine().lower()
    if machine not in ('amd64', 'x86_64'): raise SystemExit('This release recipe currently supports x86-64 only.')
    system = {'Windows': 'windows', 'Linux': 'linux'}.get(platform.system())
    if not system: raise SystemExit('Build on native Windows or Linux.')
    version = '0.1.0-alpha.1'
    if __version__ != '0.1.0a1': raise SystemExit('Update the explicit release/PEP 440 version mapping.')
    commit = git('rev-parse', 'HEAD')
    output = args.output.resolve()
    if output.is_relative_to(ROOT): raise SystemExit('Build output must be outside the source tree.')
    output.mkdir(parents=True, exist_ok=True)
    name = f'dyadic-matrix-{version}-{system}-x86_64'
    bundle = output / name
    work = output / (name + '-build')
    if bundle.exists() or work.exists(): raise SystemExit('Use a new output directory; existing builds are preserved.')
    bundle.mkdir();work.mkdir()
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir',
               '--name', 'dm', '--paths', str(ROOT / 'src'), '--collect-all', 'asyncpg',
               '--collect-all', 'tzdata', '--add-data', f'{ROOT / "src/dm_engine/schema.sql"}:dm_engine',
               '--add-data', f'{ROOT / "src/dm_engine/LICENSE"}:dm_engine',
               '--distpath', str(bundle / 'bin'), '--workpath', str(work / 'work'),
               '--specpath', str(work), str(ROOT / 'tools/native_entry.py')]
    subprocess.run(command, cwd=ROOT, check=True)
    # Portable archives contain ordinary files, including Linux library aliases.
    # Keep their bytes while avoiding platform-dependent symlink extraction.
    for path in (bundle / 'bin').rglob('*'):
        if path.is_symlink():
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(bundle) or not resolved.is_file():
                raise RuntimeError('Unexpected native build symlink')
            content = resolved.read_bytes();path.unlink();path.write_bytes(content)
    for name_dir in ('docs', 'examples', 'schemas'):
        shutil.copytree(ROOT / name_dir, bundle / name_dir)
    for filename in ('README.md', 'LICENSE', 'CONTRIBUTING.md'):
        shutil.copyfile(ROOT / filename, bundle / filename)
    installer = 'install.ps1' if system == 'windows' else 'install.sh'
    shutil.copyfile(ROOT / 'tools' / installer, bundle / installer)
    if system == 'linux': (bundle / installer).chmod(0o755)
    dependencies = licenses(bundle / 'third-party')
    files = {p.relative_to(bundle).as_posix(): sha(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    manifest = {'format': 1, 'version': version, 'python_package_version': __version__, 'source_commit': commit,
                'canonical_source': 'https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693',
                'github_mirror': 'https://github.com/HiLleywyn/dyadic-matrix',
                'platform': system, 'architecture': 'x86_64', 'python': platform.python_version(),
                'libc': platform.libc_ver() if system == 'linux' else None,
                'dependencies': dependencies, 'files': files}
    (bundle / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    # The shell installer needs no Python; it verifies the same payload hashes.
    (bundle / 'files.sha256').write_text(''.join(f'{value}  {path}\n' for path, value in files.items()) +
                                      f'{sha(bundle / "release.json")}  release.json\n', encoding='utf-8')
    if system == 'windows':
        archive = output / (bundle.name + '.zip')
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for path in sorted(bundle.rglob('*')):
                if path.is_file(): zipped.write(path, path.relative_to(output).as_posix())
    else:
        archive = output / (bundle.name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar: tar.add(bundle, arcname=bundle.name)
    print(json.dumps({'archive': archive.name, 'sha256': sha(archive), 'bytes': archive.stat().st_size,
                      'source_commit': commit, 'manifest_sha256': sha(bundle / 'release.json')}))


if __name__ == '__main__': main()
