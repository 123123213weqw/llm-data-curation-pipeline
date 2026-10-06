#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/packages/curation-continuous-v131:$ROOT/src:$ROOT/scripts:$ROOT/tests"
export PYTHONDONTWRITEBYTECODE=1
export TOKENIZERS_PARALLELISM=false
cd "$ROOT"
python3 -B -m unittest test_continuous test_qwen_audit_v35 test_qwen_compact_evidence_v35 -v
