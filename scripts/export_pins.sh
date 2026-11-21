#!/usr/bin/env sh
# Regenerate the version pins a standalone `docbox` (uv tool / pip install) uses to
# install engine packages: the same versions as uv.lock. CI fails if they're stale.
set -eu
cd "$(dirname "$0")/.."
pins=src/docbox/backend/core/pins
export_extras() {
  uv export --frozen --no-dev --no-emit-project --no-hashes --no-header --no-annotate "$@"
}
# The CPU builds of every engine, and the MCP server. The graphics-card builds conflict
# with them (pyproject.toml), and uv.lock pins torch differently for each, so each gets
# its own file (core/runtime.py::_pins_for).
export_extras --extra paddle --extra easyocr --extra agents > "$pins/constraints.txt"
for gpu in paddle-gpu easyocr-gpu; do
  export_extras --extra "$gpu" > "$pins/constraints-$gpu.txt"
done
# uv pip ignores [tool.uv] override-dependencies; mirror it (see pyproject.toml).
echo "opencv-python-headless ; sys_platform == 'never'" > "$pins/overrides.txt"
