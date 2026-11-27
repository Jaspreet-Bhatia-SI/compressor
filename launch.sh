#!/usr/bin/env bash
set -u

APP_DIR="/home/jass/education/projects/compressor"
PYTHON_BIN="$APP_DIR/venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

while true; do
  "$PYTHON_BIN" "$APP_DIR/main.py"
  echo
  read -r -p "Press Enter to exit (or type 'r' + Enter to compress another file): " choice || break
  if [[ "${choice,,}" != "r" ]]; then
    break
  fi
  clear
done
