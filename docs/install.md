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
dependency. Pure validation/expression evaluation has no external dependencies.

## Release packages

Versioned Windows/Linux packages, checksums, source-revision manifests and install
instructions are published through repository Releases. A release note identifies
the exact tested commands and supported operating systems/architectures; presence
of an archive alone is not installation acceptance. Release assets must match
the recorded SHA-256 and source tag. Do not substitute an unversioned executable
or silently download another build when integrity verification fails.

Windows can calculate an archive digest using
`Get-FileHash FILE -Algorithm SHA256`; Linux can use `sha256sum FILE`.
The release build does not use GitHub Actions. Native Windows and isolated Linux
builds are tested separately before their artifacts receive the same source tag.
