# Continuous curation v139

Independent successor to v136. Does not restart, replay or mutate prior jobs.
Original complete-body compact64 teacher protocol, eight QA workers per backend,
quality thresholds, inventory isolation, single publisher and physical 4096-token
pack checks remain unchanged. No paid teacher calls or training.

## Data flow

1. CPU selects new unallocated stock, excluding every earlier allocation/body/key.
2. CPU prepares complete candidates and original review Batch on disk (queue ≤ 4).
3. CPU verifies **all** candidate/allocation/review files against CPU manifest.
4. Compressed transport sends only full review and immutable metadata/proofs.
   Candidate parquet and full allocation/history arrays stay on the CPU host.
5. GPU validates every review SHA and actual protocol key, authenticates absence
   against the full historical exclusion set, then persistently reserves unique
   bodies/keys across all lanes before its once-only original teacher call.
6. Complete private ledger/physical receipts return for original CPU quality,
   exact/near/eval/family/split/heldout filtering, packing and single-writer publish.
7. READY is counted only after original receipt/SQL/train-body/pack verification.

## Exact compact history proof

`portable.py` commits the complete sorted historical body/key sets to domain-separated
SHA256 Merkle roots. Authenticated adjacent neighbors or first/last boundaries
prove nonmembership in the **full** set, not a sample. The descriptor SHA is frozen
in both controller configs. CPU retains full sorted vectors and all index hashes.
GPU independently recomputes the original full Batch's body/key list; its durable
unique SQLite reservation prevents cross-lane same-run replay, including unknowns.

## Producer termination

`drain.py` requires producer's sealed job list to exactly match the durable queue.
End notification waits until every item is sent or explicitly held. Controller exit
also requires import/terminal observation and completion of the publisher queue.
A producer-end race can no longer forget a late queue item. HOLD is not READY.

## Tests

Fixture-only tests run on remote hosts, never teacher calls. They cover adversarial
Merkle tampering, boundaries/odd nodes, exact full-set equivalence, persistent and
concurrent reservations, CPU/GPU manifest split, late-queue drain, and inherited
protocol/transport/grounding gates. Real-size history and compressed cross-host
review transport must pass before any new controller is launched.

## Production import boundary fix

`gpu.original_protocol_runtime()` inserts the frozen payload engine's `src/` and
`scripts/` paths explicitly. It is tested with an isolated `python -I -B` child,
empty `PYTHONPATH`, unrelated working directory, and a real original 512-document
Batch on both hosts. GPU startup resolves the original Batch/protocol/key modules
before creating its run intent; the consumer uses the same function before any
reservation or teacher request. v136's pre-request module failures and every
allocation are preserved/excluded; no old teacher or transport attempt is replayed.
