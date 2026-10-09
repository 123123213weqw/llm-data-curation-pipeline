#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
cd "$ROOT"
for VERSION in 144 146; do
  echo "=== public v${VERSION} synthetic controller suite ==="
  PYTHONPATH="$ROOT/packages/curation-continuous-v${VERSION}:$ROOT/src:$ROOT/scripts:$ROOT/tests" \
    python3 -B -m unittest discover -s "$ROOT/packages/curation-continuous-v${VERSION}" -p 'test_*.py' -v
done
python3 -B tools/verify_source_manifest.py
