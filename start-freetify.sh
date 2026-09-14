#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Freetify is not installed yet. Create a virtual environment and install requirements.txt first."
  exit 1
fi

exec ".venv/bin/python" server.py
