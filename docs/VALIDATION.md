# Latest snapshot validation — v144/v146

2026-10-09 public export validation:

- All **35 v144 + 37 v146 Python controller/test files** matched the frozen CPU CONFIG code bindings and independently read GPU-host files by SHA-256.
- **168 exported current files** matched bound controller/engine source SHA; this count excludes private runtime inputs and unrelated training modules. `SOURCE_MANIFEST.json` verifies **210 public source/template files**, including retained history.
- Only infrastructure path/SSH-alias literals were normalized in public copies. Original source hashes, public hashes and edit counts are recorded per file. Production sources were not modified.
- Python AST and JSON parsing passed. Credential/private-key/private-machine-path scans passed. Human authorization, runtime CONFIG/intent, corpus, model weights and private ledgers were excluded.
- **Actual remote Linux tests on the sanitized public copy: 401 passed**:
  - v144 controller suite: **171 passed**.
  - v146 controller suite: **184 passed**.
  - original release/parallel-CPU suite: **46 passed**, including the Linux RLIMIT_AS reference sandbox. No memory guard was weakened.
- Suites used synthetic fixtures, temporary SQLite and loopback mock servers. No production teacher, training, systemd start/restart, Rust compile or production corpus access was performed.
- Testing occurred in an isolated remote build directory, not in a frozen running pipeline directory.
- This is a review snapshot, not an end-to-end deployable production bundle. Passing fixture tests does not establish production throughput or quality-gate acceptance for new sources.

```bash
python3 -B tools/verify_source_manifest.py
bash tools/run_current_tests.sh
bash tools/run_release_tests_linux.sh
```

## Historical validation (v131 export)

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
