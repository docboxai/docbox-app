#!/usr/bin/env bash
# Run the uv inside each built Linux package (AppImage, .deb, .rpm) and check it's the
# pinned version. Packaging can break a program that ran fine before it was bundled: the
# AppImage step adds a library path to everything in usr/bin, which made the static musl
# uv crash on start. The release workflow runs this before uploading anything.
#
# Usage: scripts/check_bundled_uv.sh <bundle dir> <uv version>
# e.g.   scripts/check_bundled_uv.sh src-tauri/target/release/bundle 0.12.3
# Needs dpkg-deb, rpm2cpio and cpio.
set -euo pipefail
bundle=$(cd "$1" && pwd)
want="uv $2 "
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
shopt -s nullglob

checked=0
check() {  # <package file> <its uv>
  local out status=0
  out=$("$2" --version 2>&1) || status=$?
  if [ "$status" -ne 0 ] || [[ "$out" != "$want"* ]]; then
    echo "::error::The uv in $(basename "$1") doesn't run as expected: exit status $status, printed \"$out\" (expected \"$want...\")"
    exit 1
  fi
  echo "$(basename "$1"): $out"
  checked=$((checked + 1))
}

for f in "$bundle"/appimage/*.AppImage; do
  dir="$work/$(basename "$f")"
  mkdir "$dir"
  # Extracting needs no FUSE. It unpacks into ./squashfs-root.
  (cd "$dir" && "$f" --appimage-extract >/dev/null)
  check "$f" "$dir/squashfs-root/usr/bin/uv"
done
for f in "$bundle"/deb/*.deb; do
  dir="$work/$(basename "$f")"
  dpkg-deb -x "$f" "$dir"
  check "$f" "$dir/usr/bin/uv"
done
for f in "$bundle"/rpm/*.rpm; do
  dir="$work/$(basename "$f")"
  mkdir "$dir"
  (cd "$dir" && rpm2cpio "$f" | cpio -idm --quiet)
  check "$f" "$dir/usr/bin/uv"
done

[ "$checked" -gt 0 ] || { echo "::error::No AppImage, .deb or .rpm under $bundle"; exit 1; }
