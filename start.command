#!/bin/bash
# Launch the UI at http://127.0.0.1:8765  (macOS: double-click this file)
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || { echo "Run ./setup.sh first"; exit 1; }
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
(sleep 2; command -v open >/dev/null && open http://127.0.0.1:8765) &
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8765
