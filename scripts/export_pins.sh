#!/usr/bin/env sh
# Regenerate the version pins a standalone `docbox` (uv tool / pip install) uses to
# install engine packages: the same versions as uv.lock. CI fails if they're stale.
set -eu
cd "$(dirname "$0")/.."
pins=src/docbox/backend/core/pins
uv export --frozen --all-extras --no-dev --no-emit-project --no-hashes --no-header \
  --no-annotate > "$pins/constraints.txt"
# uv pip ignores [tool.uv] override-dependencies; mirror it (see pyproject.toml).
echo "opencv-python-headless ; sys_platform == 'never'" > "$pins/overrides.txt"
