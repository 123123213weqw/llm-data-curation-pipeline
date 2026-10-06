#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo 'Release reference sandbox needs Linux RLIMIT_AS; do not weaken its memory guard to run on macOS.' >&2
  exit 2
fi
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/packages/curation-continuous-v131:$ROOT/src:$ROOT/scripts:$ROOT/tests"
export PYTHONDONTWRITEBYTECODE=1
cd "$ROOT"
python3 -B -m unittest test_release_gates_v5 test_parallel_cpu_v13 test_parallel_cpu_v15 test_qwen_overnight_slot_v67 -v
