"""Fail-closed SFT pilot adapter. No network, teacher calls, or training loop.

This format is deliberately separate from pretraining train-body accounting.
Quality acceptance, training approval and a verified physical pack are distinct.
"""
import hashlib
import json
import re
import struct
import unicodedata
from pathlib import Path

IGNORE = -100
FORMAT = "sft_assistant_mask_4096_v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def freeze(path, value):
    with Path(path).open("x") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        import os
        os.fsync(f.fileno())


def validate_messages(messages):
    if not isinstance(messages, list) or not messages:
        raise ValueError("empty conversation")
    turns = []
    for i, m in enumerate(messages):
        if set(m) != {"role", "content"} or not isinstance(m["content"], str) or not m["content"].strip():
            raise ValueError("invalid message")
        if m["role"] == "system":
            if i != 0:
                raise ValueError("system must be first")
        elif m["role"] in ("user", "assistant"):
            turns.append(m["role"])
        else:
            raise ValueError("unknown role")
        if any(s in m["content"] for s in ("<|system|>", "<|user|>", "<|assistant|>", "<|end|>", "<eos>")):
            raise ValueError("reserved token literal")
    if not turns or len(turns) % 2 or turns != ["user", "assistant"] * (len(turns) // 2):
        raise ValueError("unpaired conversation")


def encode_conversation(messages, tokenizer, limit=4096):
    validate_messages(messages)
    for token, expected in (("<|system|>", 4), ("<|user|>", 5), ("<|assistant|>", 6), ("<|end|>", 9), ("<eos>", 2)):
        if tokenizer.token_to_id(token) != expected:
            raise ValueError("student token identity mismatch")
    ids, labels = [], []
    for m in messages:
        header = tokenizer.encode("<|" + m["role"] + "|>\n", add_special_tokens=False).ids
        content = tokenizer.encode(m["content"] + "\n", add_special_tokens=False).ids
        ids.extend(header + content + [9])
        labels.extend([IGNORE] * len(header))
        labels.extend(content + [9] if m["role"] == "assistant" else [IGNORE] * (len(content) + 1))
    ids.append(2)
    labels.append(2)
    if len(ids) > limit:
        raise ValueError("full conversation exceeds limit; never truncate")
    validate_record(ids, labels, limit)
    return ids, labels


def validate_record(ids, labels, limit=4096):
    if not ids or len(ids) != len(labels) or len(ids) > limit or labels[0] != IGNORE or ids[-1] != 2 or labels[-1] != 2:
        raise ValueError("invalid causal record")
    if any(type(x) is not int or not 0 <= x < 2**31 for x in ids):
        raise ValueError("invalid token")
    if any(type(y) is not int or (y != IGNORE and y != x) for x, y in zip(ids, labels)):
        raise ValueError("target identity mismatch")
    if not any(y != IGNORE for y in labels[1:-1]):
        raise ValueError("empty assistant target")


def validate_cached_keep(row, result):
    validate_messages(row["messages"])
    a = result.get("annotation", {})
    if result.get("state") != "VALID" or result.get("row_id") != row["id"]:
        raise ValueError("unknown/invalid/mismatched cache is never reused")
    if a.get("decision") != "keep" or a.get("instruction_following") is not True or a.get("correctness") != "supported" or a.get("issues") != []:
        raise ValueError("not a valid keep")
    roles = set()
    evidence = a.get("evidence", [])
    if not 2 <= len(evidence) <= 6:
        raise ValueError("evidence count")
    for e in evidence:
        i, quote = e.get("message_index"), e.get("quote")
        if type(i) is not int or not 0 <= i < len(row["messages"]) or not isinstance(quote, str) or not quote or quote not in row["messages"][i]["content"]:
            raise ValueError("ungrounded cached quote")
        roles.add(row["messages"][i]["role"])
    if not {"user", "assistant"} <= roles:
        raise ValueError("user and assistant evidence required")


def approved_cells(rows, results):
    groups = {}
    for row in rows:
        key = (row["source_repository"], row["domain"], row["length_stratum"])
        groups.setdefault(key, []).append(row)
    out = {}
    for key, cell in groups.items():
        valid = sum(results.get(r["id"], {}).get("state") == "VALID" for r in cell)
        keep = sum(results.get(r["id"], {}).get("state") == "VALID" and results[r["id"]].get("annotation", {}).get("decision") == "keep" for r in cell)
        out[key] = {"selected": len(cell), "valid": valid, "keep": keep,
                    "passed": len(cell) == 64 and valid == 64 and keep >= 61}
    return out


def safety_hits(messages):
    # Pattern screening, not a claim of exhaustive PII or semantic redaction.
    s = "\n".join(m["content"] for m in messages)
    patterns = {
        "email": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "phone_zh": r"(?<!\d)1[3-9]\d{9}(?!\d)",
        "id_card_zh": r"(?<!\d)\d{17}[\dXx](?!\d)",
        "credential": r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bgh[pousr]_[A-Za-z0-9]{25,}|AKIA[0-9A-Z]{16}",
        "assignment_secret": r"(?i)(?:api[_ -]?key|password|passwd|secret[_ -]?key)\s*[:=]\s*['\"]?[^\s'\"]{8,}",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, s)]


def normalized(text):
    return " ".join(unicodedata.normalize("NFKC", text).lower().split())


def prompt_simhash(text):
    words = normalized(text).split()
    votes = [0] * 64
    for w in set(words):
        h = int.from_bytes(hashlib.sha256(w.encode()).digest()[:8], "big")
        for i in range(64):
            votes[i] += 1 if h >> i & 1 else -1
    return sum(1 << i for i, v in enumerate(votes) if v >= 0)


def split_hits(row, sealed):
    p = next(m["content"] for m in row["messages"] if m["role"] == "user")
    n, h = normalized(p), prompt_simhash(p)
    return [r["id"] for r in sealed if n == normalized(next(m["content"] for m in r["messages"] if m["role"] == "user")) or
            (h ^ prompt_simhash(next(m["content"] for m in r["messages"] if m["role"] == "user"))).bit_count() <= 3]


def pack_write(directory, rows, tokenizer_sha):
    directory = Path(directory)
    directory.mkdir(exist_ok=False)
    seen, index = set(), []
    with (directory / "records.bin").open("xb") as f:
        for row in rows:
            if row["id"] in seen:
                raise ValueError("duplicate pack id")
            seen.add(row["id"])
            ids, labels = row["input_ids"], row["labels"]
            validate_record(ids, labels)
            data = struct.pack("<" + "i" * (len(ids) * 2), *(ids + labels))
            index.append({"id": row["id"], "offset": f.tell(), "length": len(ids), "bytes": len(data),
                          "sha256": hashlib.sha256(data).hexdigest(), "supervised_targets": sum(x != IGNORE for x in labels)})
            f.write(data)
        f.flush()
        import os
        os.fsync(f.fileno())
    freeze(directory / "index.json", index)
    freeze(directory / "manifest.json", {"format": FORMAT, "sequence_length": 4096, "tokenizer_sha256": tokenizer_sha,
           "samples": len(index), "assistant_supervised_targets_including_end_eos": sum(x["supervised_targets"] for x in index),
           "not_pretrain_body_tokens": True, "files": {n: {"sha256": file_sha(directory / n), "bytes": (directory / n).stat().st_size} for n in ("records.bin", "index.json")}})
    return pack_read(directory, tokenizer_sha)


def pack_read(directory, tokenizer_sha):
    directory = Path(directory)
    m = json.loads((directory / "manifest.json").read_text())
    if m["format"] != FORMAT or m["sequence_length"] != 4096 or m["tokenizer_sha256"] != tokenizer_sha:
        raise ValueError("pack identity")
    if set(m["files"]) != {"records.bin", "index.json"}:
        raise ValueError("unexpected pack files")
    for n, meta in m["files"].items():
        if file_sha(directory / n) != meta["sha256"] or (directory / n).stat().st_size != meta["bytes"]:
            raise ValueError("pack SHA/size")
    index = json.loads((directory / "index.json").read_text())
    rows, offset, seen = [], 0, set()
    with (directory / "records.bin").open("rb") as f:
        for entry in index:
            n = entry["length"]
            if type(n) is not int or not 1 <= n <= 4096 or entry["bytes"] != n * 8 or entry["offset"] != offset or entry["id"] in seen:
                raise ValueError("index layout")
            seen.add(entry["id"])
            data = f.read(entry["bytes"])
            if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise ValueError("record SHA")
            v = list(struct.unpack("<" + "i" * (2 * n), data))
            ids, labels = v[:n], v[n:]
            validate_record(ids, labels)
            if sum(x != IGNORE for x in labels) != entry["supervised_targets"]:
                raise ValueError("target count")
            rows.append({"id": entry["id"], "input_ids": ids, "labels": labels})
            offset += len(data)
        if f.read(1):
            raise ValueError("trailing bytes")
    if len(rows) != m["samples"] or sum(sum(y != IGNORE for y in r["labels"]) for r in rows) != m["assistant_supervised_targets_including_end_eos"]:
        raise ValueError("manifest count")
    return rows


def collate(rows, sequence_length=4096, pad_token_id=0):
    import torch
    if not rows:
        raise ValueError("empty batch")
    for r in rows:
        validate_record(r["input_ids"], r["labels"], sequence_length)
    return {"input_ids": torch.tensor([r["input_ids"] + [pad_token_id] * (sequence_length - len(r["input_ids"])) for r in rows]),
            "labels": torch.tensor([r["labels"] + [IGNORE] * (sequence_length - len(r["labels"])) for r in rows]),
            "attention_mask": torch.tensor([[1] * len(r["input_ids"]) + [0] * (sequence_length - len(r["input_ids"])) for r in rows])}


def causal_loss(logits, labels):
    """Predict position t+1 at t. Never shift masks independently of targets."""
    import torch.nn.functional as F
    if logits.shape[:2] != labels.shape or logits.shape[1] < 2 or not (labels[:, 1:] != IGNORE).any():
        raise ValueError("causal loss shape/empty targets")
    return F.cross_entropy(logits[:, :-1].reshape(-1, logits.shape[-1]), labels[:, 1:].reshape(-1), ignore_index=IGNORE)
