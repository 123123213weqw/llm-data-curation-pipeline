"""Finite, once-only CPU integration pilot. Paths/pins come from private CONFIG.

No teacher POST, model launch, student optimization or pretraining ledger writes.
"""
import argparse
import collections
import fcntl
import json
import re
import sqlite3
import sys
import time
from pathlib import Path
from code_contracts import verify_code
from sft_adapter import *


def read(path):
    return json.loads(Path(path).read_text())


def run(root):
    root = Path(root)
    cfg = read(root / "CONFIG.json")
    for name, expected in cfg["files"].items():
        if file_sha(root / name) != expected:
            raise ValueError("frozen input mismatch: " + name)
    for path, expected in cfg["external_files"].items():
        if file_sha(path) != expected:
            raise ValueError("external frozen input mismatch: " + path)
    if (root / "RUN_INTENT.json").exists():
        raise FileExistsError("existing intent: observe only, never rerun")
    with (root / "publisher.lock").open("x") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        freeze(root / "RUN_INTENT.json", {"unix": time.time(), "scope": "finite_cached_SFT_CPU_pilot", "teacher_requests": 0, "training_started": False})
        try:
            return integrate(root, cfg)
        except BaseException as e:
            freeze(root / "FAILURE.json", {"error": repr(e), "no_retry": True})
            raise


def integrate(root, cfg):
    import torch
    from tokenizers import Tokenizer
    torch.set_num_threads(2)
    parent = root / "parent_v10"
    samples, results = read(parent / "SOURCE_SAMPLE.json"), read(parent / "source_audit_RESULTS.json")
    selection = read(parent / "SOURCE_SELECTION_PROOF.json")
    proof = read(root / "REQUESTS_VERIFIED.private.json")
    if not proof["all_completed_requests_sql_outbox_wire_sha_verified"] or not proof["no_cross_slot_duplicate_rows"] or proof["pending_not_claimed_settled"]:
        raise ValueError("parent requests not verified settled")
    verified_results = {v["result"]: v for v in proof["request_sha_map"].values()}
    if len(samples) != 768 or set(results) != {r["id"] for r in samples}:
        raise ValueError("complete source scope required")
    for row in samples:
        rec = results[row["id"]]
        rec_sha = __import__("hashlib").sha256((json.dumps(rec, ensure_ascii=False, indent=2) + "\n").encode()).hexdigest()
        if rec_sha not in verified_results or verified_results[rec_sha]["state"] != rec["state"] or rec["state"] not in ("VALID", "INVALID"):
            raise ValueError("result is not the private ledger terminal")
    if read(parent / "BASELINE_GATE.json")["status"] != "passed" or any(g["status"] != "passed" for g in read(parent / "REPLICA_GATES.json").values()):
        raise ValueError("calibrated teacher controls required")
    gates = approved_cells(samples, results)
    actual_approved = sorted(k for k, v in gates.items() if v["passed"])
    if actual_approved != [tuple(x) for x in cfg["approved_scope"]]:
        raise ValueError("approved scope mismatch")
    old = read(cfg["prior_sample"])
    if len(old) != 384 or file_sha(cfg["prior_sample"]) != selection["prior_sample_sha256"]:
        raise ValueError("old scope identity")
    exclude_ids = {r["id"] for r in old}
    exclude_bodies = {digest(r["messages"]) for r in old}
    train_path = Path(cfg["candidates"]) / "candidate_train.jsonl"
    train = [json.loads(l) for l in train_path.open()]
    if len(train) != 18089 or any(r["split"] != "train" for r in train):
        raise ValueError("train candidate scope")
    by_id = {r["id"]: r for r in train}
    membership, reconstructed, coverage = {}, [], {}
    for source in sorted({r["source_repository"] for r in train}):
        for domain in ("code", "general"):
            pool = sorted((r for r in train if r["source_repository"] == source and r["domain"] == domain and r["id"] not in exclude_ids and digest(r["messages"]) not in exclude_bodies), key=lambda r: (len(r["input_ids"]), r["id"]))
            coverage[source + "|" + domain] = {}
            for i, length in enumerate(("short", "medium", "long")):
                cell = pool[len(pool) * i // 3:len(pool) * (i + 1) // 3]
                key = source, domain, length
                for r in cell:
                    membership[r["id"]] = key
                chosen = sorted(cell, key=lambda r: digest(["domain_source_v10", source, domain, length, r["id"]]))[:64]
                for r in chosen:
                    reconstructed.append({k: r[k] for k in ("id", "messages", "source_repository", "source_revision", "source_file", "source_row", "language", "domain")} | {"length_stratum": length, "split": "train", "sft_candidate_SHA": digest(r)})
                coverage[source + "|" + domain][length] = {"pool": len(cell), "selected": len(chosen), "base_input_token_range": [min(len(r["input_ids"]) for r in cell), max(len(r["input_ids"]) for r in cell)]}
    if reconstructed != samples or coverage != selection["coverage"]:
        raise ValueError("full source selection reconstruction, including tied boundaries")
    eligible = []
    for key in actual_approved:
        cell = [r for r in samples if membership[r["id"]] == key and results[r["id"]]["state"] == "VALID" and results[r["id"]].get("annotation", {}).get("decision") == "keep"]
        eligible.extend(sorted(cell, key=lambda r: digest(["formal_cpu_pilot_v12", r["id"]]))[:cfg["per_cell"]])
    if len(eligible) != 96 or len({r["id"] for r in eligible}) != 96:
        raise ValueError("fixed pilot scope")
    freeze(root / "PILOT_SCOPE.json", {"ids": [r["id"] for r in eligible], "rows": 96, "cache_reuse_same_full_conversation_protocol": True, "source_membership_reconstructed": True, "new_teacher_requests": 0})
    tok = Tokenizer.from_file(cfg["tokenizer"])
    sealed = []
    for split in ("validation", "test"):
        sealed.extend(json.loads(l) for l in (Path(cfg["candidates"]) / ("candidate_" + split + ".jsonl")).open())
    if len(sealed) != 974 or any(r["split"] == "train" for r in sealed):
        raise ValueError("heldout scope")
    sys.path.insert(0, cfg["curation_code"])
    from small_agent.curation.release_gates_v5 import EvalScreen
    policy = read(cfg["release_policy"])["evaluation"]
    screen = EvalScreen(cfg["eval_registry"], policy)
    freeze(root / "BENCHMARK_GATE.json", {"registry_sha256": file_sha(cfg["eval_registry"]), "policy_sha256": file_sha(cfg["release_policy"]), "required_tasks": policy["required_tasks"], "actual_reference_files_sha_verified": True, "scope": "original full-phrase/word13/CJK30 lexical; not paraphrase certification", "sealed_sft_rows": len(sealed), "heldout_never_sent_to_teacher": True})
    accepted, held, audit = [], [], []
    for sample in eligible:
        row = by_id[sample["id"]]
        if digest(row) != sample["sft_candidate_SHA"] or membership[row["id"]] not in actual_approved:
            raise ValueError("candidate/cache body provenance changed")
        validate_cached_keep(sample, results[row["id"]])
        ids, labels = encode_conversation(row["messages"], tok)
        if ids != row["input_ids"] or labels != row["labels"] or sum(x != IGNORE for x in labels) != row["supervised_targets"]:
            raise ValueError("original student full-conversation/mask mismatch")
        reasons = []
        pii = safety_hits(row["messages"])
        if pii: reasons.append("PII_CREDENTIAL_PATTERN:" + ",".join(pii))
        hits = sorted(set(t for m in row["messages"] for t in screen.matches(m["content"])))
        if hits: reasons.append("BENCHMARK_OVERLAP:" + ",".join(hits))
        if split_hits(row, sealed): reasons.append("SFT_HELDOUT_EXACT_OR_LEXICAL_NEAR")
        code = {"status": "NOT_APPLICABLE"}
        if row["domain"] == "code":
            code = verify_code(row["messages"])
            if code["status"] != "PASS": reasons.append("CODE_CORRECTNESS_HOLD:" + code["reason"])
        else:
            # The pilot has no natural-math or high-stakes fact oracle: preserve such rows.
            text = "\n".join(m["content"] for m in row["messages"])
            if re.search(r"\d|计算|数学|方程|医疗|诊断|处方|投资|法律", text):
                reasons.append("UNSUPPORTED_FACT_OR_MATH_SCOPE")
        rec = {"id": row["id"], "source": row["source_repository"], "domain": row["domain"], "stratum": sample["length_stratum"], "candidate_sha256": digest(row), "cached_result_sha256": __import__("hashlib").sha256((json.dumps(results[row["id"]], ensure_ascii=False, indent=2) + "\n").encode()).hexdigest(), "code_check": code, "status": "HOLD" if reasons else "PILOT_ACCEPTED", "reasons": reasons, "assistant_targets": row["supervised_targets"]}
        audit.append(rec)
        if reasons:
            held.append(rec)
        else:
            accepted.append(row)
    freeze(root / "ROW_AUDIT.private.json", audit)
    freeze(root / "HOLD.private.json", held)
    if not accepted:
        raise ValueError("no accepted pilot records; HOLD preserved")
    loaded = pack_write(root / "pack", accepted, cfg["tokenizer_sha256"])
    if loaded != [{"id": r["id"], "input_ids": r["input_ids"], "labels": r["labels"]} for r in accepted]:
        raise ValueError("all record physical roundtrip")
    loader_count = 0
    for batch in torch.utils.data.DataLoader(loaded, batch_size=4, num_workers=0, collate_fn=collate):
        if batch["input_ids"].shape[1] != 4096 or not (batch["labels"][batch["attention_mask"] == 0] == IGNORE).all():
            raise ValueError("actual causal DataLoader padding")
        loader_count += int((batch["labels"][:, 1:] != IGNORE).sum())
    target_count = sum(r["supervised_targets"] for r in accepted)
    if loader_count != target_count:
        raise ValueError("shifted supervised-target accounting")
    freeze(root / "PHYSICAL_VERIFY.json", {"all_bin_index_sha_size": True, "all_records_full_token_mask_roundtrip": True, "actual_torch_cpu_dataloader_4096": True, "samples": len(accepted), "assistant_targets_including_end_eos": target_count, "not_pretrain_train_body": True, "tests_sha256": file_sha(root / "CPU_TESTS.txt"), "no_model_or_optimizer": True})
    bid = digest(["sft_cpu_pilot_v12", cfg["tokenizer_sha256"], [r["id"] for r in accepted]])
    receipt = {"batch_id": bid, "status": "VERIFIED_SFT_PILOT_NOT_TRAINING_APPROVAL", "samples": len(accepted), "assistant_supervised_targets_including_end_eos": target_count, "teacher_requests": 0, "training_started": False, "formal_sft_ready_samples": 0, "pilot_held": len(held), "by_scope": dict(collections.Counter(r["domain"] + "|" + membership[r["id"]][2] for r in accepted)), "evidence": {n: file_sha(root / n) for n in ("CONFIG.json", "PILOT_SCOPE.json", "BENCHMARK_GATE.json", "ROW_AUDIT.private.json", "HOLD.private.json", "PHYSICAL_VERIFY.json", "pack/manifest.json")}, "limits": ["finite 96 cached pilot, not all 19063", "lexical PII/eval checks, not exhaustive semantic or factual certification", "code: supported concrete input only; unsupported code stays HOLD", "actual student trainer registration and heldout student evaluation still required before SFT training"]}
    freeze(root / "PUBLISH_INTENT.json", {"batch_id": bid, "once_only_private_registry": True})
    freeze(root / "VERIFIED_PILOT.json", receipt)
    db = sqlite3.connect(root / "pilot.sqlite")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("CREATE TABLE batches (batch_id TEXT PRIMARY KEY,receipt_sha TEXT,samples INTEGER,assistant_targets INTEGER,status TEXT)")
    db.execute("CREATE TABLE documents(id TEXT PRIMARY KEY,batch_id TEXT,split TEXT,assistant_targets INTEGER,candidate_sha TEXT)")
    db.execute("INSERT INTO batches VALUES (?,?,?,?,?)", (bid, file_sha(root / "VERIFIED_PILOT.json"), len(accepted), target_count, receipt["status"]))
    db.executemany("INSERT INTO documents VALUES (?,?,?,?,?)", [(r["id"], bid, "train", r["supervised_targets"], digest(r)) for r in accepted])
    db.commit()
    counts = db.execute("SELECT count(*),sum(assistant_targets) FROM documents WHERE batch_id=? AND split='train'", (bid,)).fetchone()
    if counts != (len(accepted), target_count) or db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("private SFT SQL reconciliation")
    db.close()
    freeze(root / "COMPLETE.json", {"status": receipt["status"], "samples": len(accepted), "assistant_targets": target_count, "held": len(held), "batch_id": bid, "receipt_sha256": file_sha(root / "VERIFIED_PILOT.json"), "new_teacher_requests": 0, "training_started": False, "formal_sft_ready_samples": 0})
    return read(root / "COMPLETE.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    print(json.dumps(run(parser.parse_args().root)))
