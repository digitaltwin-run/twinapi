#!/usr/bin/env bash
# Kontrola pakietu z powłoki — ta sama, która ma działać w CI.
set -euo pipefail
cd "$(dirname "$0")"

case "${1:-check}" in
  check)
    echo "[twinapi] lint"
    python3 -m ruff check src tests
    ;;
  test)
    echo "[twinapi] testy"
    PYTHONPATH=src python3 -m pytest -q
    ;;
  all)
    "$0" check && "$0" test
    ;;
  *)
    echo "użycie: ./project.sh [check|test|all]" >&2
    exit 2
    ;;
esac
