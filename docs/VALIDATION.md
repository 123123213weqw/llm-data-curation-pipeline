# Snapshot validation

2026-10-06 public export validation:

- The 11 v131 controller Python files were matched by SHA-256 to the live frozen controller.
- All exported dependencies that are in the frozen production engine binding matched the production SHA-256. Unrelated training sources were not exported.
- `SOURCE_MANIFEST.json` records every exported source/template's original and public SHA-256. Infrastructure literals are normalized only in the public copy; algorithm/protocol/quality thresholds are unchanged.
- Static Python AST and JSON parse checks passed for all exported files.
- Credential/private-key and private-infrastructure-literal scans found no residual matches. No corpus, live ledger, model weights, account file, launch intent or runtime CONFIG was included.
- Public copy offline suite: **65 tests passed** (`test_continuous`, `test_qwen_audit_v35`, `test_qwen_compact_evidence_v35`). This does not invoke a real teacher, create systemd services, train a model or compile Rust.
- Additional release/parallel-CPU suite on the exporting macOS host: **45 passed, 1 failed due to unsupported RLIMIT_AS semantics** (`test_external_reference_execution`, `ValueError: current limit exceeds maximum limit`). Its Linux memory guard was deliberately not weakened. Run `tools/run_release_tests_linux.sh` on Linux; no claim is made that this additional public-copy suite passed remotely.
- No end-to-end production run of this public snapshot was attempted. The production copy is separate and unchanged.

Commands:

```bash
python3 tools/verify_source_manifest.py
bash tools/run_offline_tests.sh
# Linux only:
bash tools/run_release_tests_linux.sh
```
