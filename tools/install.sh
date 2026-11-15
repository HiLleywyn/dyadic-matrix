#!/bin/sh
set -eu
source_root=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd -P)
install_root=${1:-"$HOME/.local/share/dyadic-matrix"}
cd "$source_root"
test -z "$(find . -type l -print -quit)" || { echo 'Package contains a symbolic link' >&2; exit 1; }
sha256sum --strict --check files.sha256 >/dev/null
# Version is written by the committed release recipe; accept no path syntax.
version=$(sed -n 's/^  "version": "\([0-9][0-9.]*-alpha\.[0-9][0-9]*\)",$/\1/p' release.json)
test -n "$version" || { echo 'Unexpected release version' >&2; exit 1; }
destination=$(realpath -m -- "$install_root/$version")
case "$destination/" in "$source_root/"*) echo 'Install root must be outside the extracted package' >&2; exit 1;; esac
test ! -e "$destination" || { echo 'Version already exists; choose another install root.' >&2; exit 1; }
mkdir -p -- "$destination"
cp -R -- . "$destination/"
"$destination/bin/dm/dm" --version
printf 'Installed: %s/bin/dm/dm\nAdd this directory to PATH: %s/bin/dm\n' "$destination" "$destination"
