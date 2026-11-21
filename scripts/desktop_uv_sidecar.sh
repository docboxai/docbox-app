#!/usr/bin/env sh
# For local installer builds: copy the uv on PATH to desktop/binaries/uv-<target-triple>,
# where cargo-packager looks for the bundled uv. Release CI downloads a pinned,
# checksum-verified uv there instead.
set -eu
cd "$(dirname "$0")/../desktop"
triple=$(rustc -vV | sed -n 's/^host: //p')
ext=""
case "$triple" in *windows*) ext=".exe" ;; esac
mkdir -p binaries
cp "$(command -v uv)" "binaries/uv-$triple$ext"
echo "binaries/uv-$triple$ext"
