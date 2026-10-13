import copy
import json
import tempfile
import unittest
from pathlib import Path
from sft_adapter import *
from code_contracts import verify_code


class Tokenizer:
    def token_to_id(self, token):
        return {"<|system|>": 4, "<|user|>": 5, "<|assistant|>": 6, "<|end|>": 9, "<eos>": 2}[token]

    def encode(self, text, add_special_tokens=False):
        class Encoded:
            ids = [10 + ord(c) % 60 for c in text]
        return Encoded()


class Tests(unittest.TestCase):
    def setUp(self):
        self.ms = [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}]
        self.row = {"id": "x", "messages": self.ms}
        self.result = {"row_id": "x", "state": "VALID", "annotation": {"decision": "keep", "instruction_following": True, "correctness": "supported", "issues": [], "evidence": [{"message_index": 0, "quote": "Question"}, {"message_index": 1, "quote": "Answer"}]}}

    def test_render(self):
        ids, labels = encode_conversation(self.ms, Tokenizer())
        self.assertEqual(ids[-2:], [9, 2]); self.assertEqual(labels[-2:], [9, 2])
        self.assertTrue(all(y == -100 for y in labels[:len("<|user|>\nQuestion\n") + 1]))

    def test_no_truncation(self):
        with self.assertRaises(ValueError): encode_conversation(self.ms, Tokenizer(), 4)

    def test_role_reject(self):
        with self.assertRaises(ValueError): validate_messages(self.ms[::-1])

    def test_reserved_literal(self):
        self.ms[1]["content"] = "<eos>"
        with self.assertRaises(ValueError): validate_messages(self.ms)

    def test_system_mask(self):
        ids, labels = encode_conversation([{"role": "system", "content": "Policy"}] + self.ms, Tokenizer())
        self.assertTrue(all(x == -100 for x in labels[:len("<|system|>\nPolicy\n") + 1]))

    def test_multi_turn(self):
        ids, labels = encode_conversation(self.ms * 2, Tokenizer()); self.assertEqual(ids.count(9), 4)

    def test_cache(self): validate_cached_keep(self.row, self.result)

    def test_unknown_cache(self):
        self.result["state"] = "UNKNOWN"
        with self.assertRaises(ValueError): validate_cached_keep(self.row, self.result)

    def test_invalid_cache(self):
        self.result["state"] = "INVALID"
        with self.assertRaises(ValueError): validate_cached_keep(self.row, self.result)

    def test_evidence(self):
        self.result["annotation"]["evidence"][1]["quote"] = "invented"
        with self.assertRaises(ValueError): validate_cached_keep(self.row, self.result)

    def test_false_keep(self):
        self.result["annotation"]["issues"] = ["wrong"]
        with self.assertRaises(ValueError): validate_cached_keep(self.row, self.result)

    def test_gate_invalid_denominator(self):
        rows = [dict(self.row, id=str(i), source_repository="s", domain="c", length_stratum="l") for i in range(64)]
        res = {r["id"]: dict(self.result, row_id=r["id"]) for r in rows}; res["0"]["state"] = "INVALID"
        self.assertFalse(approved_cells(rows, res)[("s", "c", "l")]["passed"])

    def test_gate_keep_min(self):
        rows = [dict(self.row, id=str(i), source_repository="s", domain="c", length_stratum="l") for i in range(64)]
        res = {r["id"]: copy.deepcopy(self.result) for r in rows}
        for i in range(4): res[str(i)]["annotation"]["decision"] = "drop"
        self.assertFalse(approved_cells(rows, res)[("s", "c", "l")]["passed"])

    def test_safety(self): self.assertEqual(safety_hits([{"content": "a@b.com"}]), ["email"])
    def test_credentials(self): self.assertIn("credential", safety_hits([{"content": "sk-" + "x" * 30}]))
    def test_split(self): self.assertEqual(split_hits(self.row, [self.row]), ["x"])

    def test_pack_roundtrip_and_tamper(self):
        ids, labels = encode_conversation(self.ms, Tokenizer())
        row = dict(self.row, input_ids=ids, labels=labels)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pack"; self.assertEqual(pack_write(p, [row], "tok")[0]["labels"], labels)
            with (p / "records.bin").open("ab") as f: f.write(b"x")
            with self.assertRaises(ValueError): pack_read(p, "tok")

    def test_duplicate_pack(self):
        ids, labels = encode_conversation(self.ms, Tokenizer()); row = dict(self.row, input_ids=ids, labels=labels)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): pack_write(Path(d) / "pack", [row, row], "tok")

    def test_target_identity(self):
        with self.assertRaises(ValueError): validate_record([10, 11, 2], [-100, 12, 2])

    def test_actual_causal_loss_gradient(self):
        import torch
        labels = torch.tensor([[-100, -100, 3, -100, 2, -100]])
        logits = torch.zeros(1, 6, 8, requires_grad=True)
        loss = causal_loss(logits, labels); loss.backward()
        self.assertAlmostEqual(loss.item(), __import__("math").log(8), places=5)
        for pos in (0, 2, 4, 5): self.assertEqual(logits.grad[0, pos].abs().sum().item(), 0)
        for pos in (1, 3): self.assertGreater(logits.grad[0, pos].abs().sum().item(), 0)

    def test_padding_and_loader(self):
        import torch
        ids, labels = encode_conversation(self.ms, Tokenizer())
        r = dict(self.row, input_ids=ids, labels=labels)
        batch = next(iter(torch.utils.data.DataLoader([r], batch_size=1, collate_fn=collate)))
        self.assertEqual(batch["labels"].shape, (1, 4096)); self.assertEqual(batch["attention_mask"].sum(), len(ids))
        self.assertTrue((batch["labels"][0, len(ids):] == -100).all())

    def code(self, src):
        return [{"role": "user", "content": "计算输入列表中所有数字的总和 输入：[1, 2, 3]"}, {"role": "assistant", "content": "```python\n" + src + "\n```"}]

    def test_code_sum(self): self.assertEqual(verify_code(self.code("numbers = [1, 2, 3]\nprint(sum(numbers))"))["status"], "PASS")
    def test_code_wrong(self): self.assertEqual(verify_code(self.code("print(8)"))["status"], "HOLD")
    def test_code_no_import(self): self.assertEqual(verify_code(self.code("import os\nprint(6)"))["status"], "HOLD")
    def test_code_no_exec(self): self.assertEqual(verify_code(self.code("exec('print(6)')"))["status"], "HOLD")
    def test_code_no_while(self): self.assertEqual(verify_code(self.code("while True:\n    pass"))["status"], "HOLD")
    def test_code_function(self): self.assertEqual(verify_code(self.code("def total(nums):\n    return sum(nums)"))["status"], "PASS")
    def test_nested_return_is_unsupported(self):
        self.assertEqual(verify_code(self.code("def total(nums):\n    for n in nums:\n        return n\n    return sum(nums)"))["status"], "HOLD")

    def test_code_budget(self): self.assertEqual(verify_code(self.code("print(10**100000000)"))["status"], "HOLD")
    def test_unsupported_spec(self): self.assertEqual(verify_code(self.ms)["status"], "HOLD")


if __name__ == "__main__": unittest.main()
