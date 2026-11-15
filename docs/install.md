# Install and verify

Source repositories:
[lley.cat](https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693)
and [GitHub](https://github.com/HiLleywyn/dyadic-matrix).
The hosted guide is [Dyadic Matrix](https://dyadic.app/developers/matrix/).

## Source installation

On Windows, use Python 3.12 or newer:

```powershell
git clone https://github.com/HiLleywyn/dyadic-matrix.git
Set-Location dyadic-matrix
py -m pip install .
dm --version
dm validate examples/native-data.dm
```

On Linux:

```sh
git clone https://github.com/HiLleywyn/dyadic-matrix.git
cd dyadic-matrix
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
dm --version
dm validate examples/native-data.dm
```

For a source checkout without installation, set `PYTHONPATH=src` and run
`python -m dm_engine`. PostgreSQL adapters use the optional `.[postgres]`
dependency. Validation and expression evaluation need no database or effect
adapter. The package includes IANA time-zone data for portable schedule checks.

## Release packages

Download from [canonical Releases](https://git.lley.cat/r/9ae6eb36-985a-4fd3-a22a-6449cdf47693?tab=releases)
or [GitHub Releases](https://github.com/HiLleywyn/dyadic-matrix/releases).
The release version `0.1.0-alpha.1` maps to Python package version `0.1.0a1`;
this is an application release number, not a language opt-in.

Versioned Windows/Linux x86-64 packages contain the Python runtime, PostgreSQL
driver and portable time-zone data. You do not need to install Python. A local
PostgreSQL database is still required for durable execution; source validation
and expression evaluation work offline without a database. Linux packages target
glibc 2.36 or newer, as used by Debian 12, and are not Alpine/musl binaries.
A release note identifies
the exact tested commands and supported operating systems/architectures; presence
of an archive alone is not installation acceptance. Release assets must match
the recorded SHA-256 and source tag. Do not substitute an unversioned executable
or silently download another build when integrity verification fails.

Windows can calculate an archive digest using
`Get-FileHash FILE -Algorithm SHA256`; Linux can use `sha256sum FILE`.
The release build does not use GitHub Actions. Native Windows and isolated Linux
builds are tested separately before their artifacts receive the same source tag.

Verify the downloaded archive against `SHA256SUMS` obtained from the release.
Checksums detect corruption; trust in the release still depends on the source
host and your download channel. These alpha binaries do not claim Authenticode
or Linux package-manager signing.

On Windows, extract the ZIP, enter its directory and run:

```powershell
.\bin\dm\dm.exe --version
.\bin\dm\dm.exe validate .\examples\schedules.dm
# Optional per-user copy; does not change PATH or require administrator rights.
.\install.ps1
```

On Linux, extract the tarball and enter its directory:

```sh
./bin/dm/dm --version
./bin/dm/dm validate examples/schedules.dm
# Optional per-user copy; prints the directory to add to PATH.
./install.sh
```

Both installers validate payload hashes, preserve existing version directories,
and accept a custom installation root as their first argument (`-InstallRoot`
on Windows). Keep the complete `bin/dm` directory together. The portable command
works directly without running the installer. `release.json` lists the exact
source commit, runtime/build dependency versions and hashes of included files;
third-party license texts are in `third-party/`.

For removal, delete only the version directory you installed and remove any PATH
entry you added yourself. The installer does not create background services,
alter a database, or remove older versions. It intentionally leaves policy,
credentials and PostgreSQL setup to the operator.

## Rebuild the packages

Use a clean checkout of the release tag. On native Windows, create an isolated
Python environment, install `tools/build-requirements.txt`, then run:

```powershell
python tools/build_release.py --output C:\builds\dyadic-matrix
```

For Linux, the committed Dockerfile pins the public Python base image digest:

```sh
docker build -f tools/Dockerfile.release -t dm-build .
docker run --rm --network none -v "$PWD:/src:ro" -v "$PWD/../dm-builds:/out" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/src \
  dm-build python tools/build_release.py --output /out
```

Dependency installation needs network access while preparing the image. The
native build itself runs offline. Build output must be outside the source tree.
The two OS builds need not be byte-identical; manifests tie each archive to the
same source revision. Before publication, run the real CLI database tests with
`DM_TEST_EXECUTABLE` set to the built executable and `DM_TEST_DSN` pointing only
at an explicitly disposable PostgreSQL fixture.
