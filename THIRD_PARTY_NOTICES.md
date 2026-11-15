# Third-party notices

Project-authored Dyadic Matrix code and documentation use the root MIT license.
Native distributions also contain independently licensed dependencies. Their
original terms and notices are retained; the root MIT license does not replace
them.

`third-party/` in a native package contains the CPython license, its incorporated
software acknowledgements, dependency metadata license texts and PyInstaller's
bootloader exception. CPython runtime code is unmodified. The bundled application
code and module selection are produced by PyInstaller from this repository.

Windows packages preserve CPython's Windows redistribution conditions and use
the OpenSSL libraries supplied with that Python installation. Linux packages
retain the actual Debian package copyright notices, versions and referenced
common license texts for the bundled shared libraries. A distribution notice
may describe other components from the upstream source package; it does not mean
that every program in that source package is part of Dyadic Matrix.

Upstream acknowledgement documents fetched into `tools/third-party/` include
their source URLs and hashes in `sources.json`. Native `release.json` records
every delivered notice file's hash. The package's `README.md` and installation
guide describe the application, platforms and runtime requirements separately.
