#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Freetify is not installed yet. Create a virtual environment and install requirements.txt first."
  exit 1
fi

nohup ".venv/bin/python" server.py > freetify.log 2>&1 &
echo "Freetify is running in the background. Logs: $(pwd)/freetify.log"
