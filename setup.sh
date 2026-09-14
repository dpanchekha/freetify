#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Python 3 is required but was not found. Install Python 3 and run this again."
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Creating Freetify virtual environment..."
  "$PYTHON" -m venv .venv
fi

echo "Installing Freetify requirements..."
".venv/bin/python" -m pip install --upgrade pip
".venv/bin/python" -m pip install -r requirements.txt

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 18+ (including npm) is required for Steam/CS2 match sync. Install Node.js, then run this script again."
  exit 1
fi

echo "Installing local Steam/CS2 bridge..."
npm ci --omit=dev

echo
echo "Freetify is ready. Start it with:"
echo "  ./start-freetify.sh"
