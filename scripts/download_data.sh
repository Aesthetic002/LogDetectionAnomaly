#!/usr/bin/env bash
# Thin wrapper so the Makefile / notes' `bash scripts/download_data.sh` works everywhere.
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/download_data.py "$@"
