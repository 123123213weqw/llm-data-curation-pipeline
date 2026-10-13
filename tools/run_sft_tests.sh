#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../packages/sft-acceptance-v13"
PYTHONDONTWRITEBYTECODE=1 CUDA_VISIBLE_DEVICES= TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=2 python -B -m unittest test_sft_adapter test_judge test_token_count -v
