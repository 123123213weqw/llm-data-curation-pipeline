# SFT review validation — 2026-10-13

- Independent remote Linux CPU v12 pilot tests: **88 passed**, 5.574 seconds.
- Independent code-only v13 review tests: **89 passed**, 4.509 seconds; no real-data run or teacher replay.
- Actual v12 CPU pilot: fixed **96** existing reviewed train samples; **28 general/short** accepted into a verified private pilot pack, **946 assistant supervised targets including end/EOS**; **68 HOLD** (64 code / 4 general). Two code samples also matched the original benchmark screen and remain held.
- Receipt SHA, isolated pilot SQLite sample/target totals, full binary/index SHA/size, every token/mask record, original tokenizer identity, registered evaluation reference SHA, and original evaluation module SHA reverified after the real unit exited with status 0.
- Real PyTorch CPU DataLoader emits 4096 records; synthetic shifted-cross-entropy checks verify zero gradients for ignored targets/padding and nonzero gradients only for supervised causal positions. No student model/optimizer loaded.
- Formal SFT training-approved READY: **0**. No student training, no new teacher request, no old partial rerun, no automatic monitor restoration.

v13 hardens the bounded code interpreter by rejecting return inside a loop instead of modeling it incorrectly. It is separately tested and **not deployed into frozen v12**; the v12 accepted pilot contains no code records. Public source copies match the remote-tested v13 review source hashes in `SFT_SOURCE_MANIFEST.json`.

This adds an SFT review suite; it does not imply the historical 401-test pretraining suite was rerun in this request. True corpus and runtime evidence remain private.
