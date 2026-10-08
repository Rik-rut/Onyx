#!/usr/bin/env bash
set -u

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. Install it with:"
    echo '  curl -LsSf https://astral.sh/uv/install.sh | sh'
    echo "Then re-run this script."
    exit 1
fi

uv python find 3.11 >/dev/null 2>&1 || echo "No Python 3.11 found; uv will fetch one automatically on first sync."

uv sync || { rc=$?; echo "uv sync failed with exit code $rc."; exit $rc; }

if [ "$#" -eq 0 ]; then
    uv run arr --help
else
    uv run arr "$@"
fi
rc=$?
if [ "$rc" -ne 0 ]; then
    echo
    echo "arr exited with code $rc."
fi
exit $rc
