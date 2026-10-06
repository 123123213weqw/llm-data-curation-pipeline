"""Offline candidate tests only, not independent quality or production approval."""
import copy
import json
import unittest
from unittest.mock import patch
from small_agent.curation import evidence_ids_qwen_v35 as adapter
from small_agent.curation import evidence_ids_qwen_v25 as old_adapter
from small_agent.curation.core import normalize_document, fingerprint
import test_evidence_ids_v8 as oldtests
from test_qwen_audit_v25 import judge as old_judge


def judge():
    j = old_judge()
    j['generation']['evidence_id_transport'] = adapter.extension()
    return j


class CompactConservativeTests(oldtests.ConservativeAdapterTests):
    def setUp(self):
        for name in ('spans', 'resolve', 'extension', 'wire_schema', 'request_body', 'validate_receipt'):
            p = patch.object(oldtests, name, getattr(adapter, name))
            p.start()
            self.addCleanup(p.stop)

    def fixture(self):
        d, _, label = super().fixture()
        return d, judge(), label

    def test_exact_body_and_all_other_fields_preserved(self):
        text = ''.join(f'记录{i}: def function_{i}(x):\n    return x + {i}\t# α\n' for i in range(400))
        d = normalize_document(dict(document_text=text, source_id='fixture', source_locator='fixture:long', language='zh', content_kind='text'))
        p = json.loads(adapter.request_body(d, 'prompt', oldtests.S, judge())['messages'][1]['content'])
        original = json.loads(d['review_payload'])
        actual = p.pop('evidence_spans')
        self.assertEqual(p, original)
        self.assertEqual(p['document_text'], text)
        self.assertEqual(len(actual), 64)
        old = old_adapter.spans(d)
        self.assertEqual((actual[0], actual[-1]), (old[0], old[-1]))
        for entry in actual:
            self.assertEqual(text[entry['start']:entry['end']], entry['text'])
            self.assertEqual(text.find(entry['text'], entry['start']+1), -1)

    def test_old_and_new_protocol_identities_never_interchange(self):
        d, j, _ = self.fixture()
        old = old_judge()
        self.assertNotEqual(fingerprint(j), fingerprint(old))
        with self.assertRaises(ValueError):
            adapter.request_body(d, 'p', oldtests.S, old)
        with self.assertRaises(ValueError):
            old_adapter.request_body(d, 'p', oldtests.S, j)
        self.assertNotEqual(fingerprint(adapter.request_body(d, 'p', oldtests.S, j)), fingerprint(old_adapter.request_body(d, 'p', oldtests.S, old)))

    def test_unknown_evidence_id_cannot_be_accepted(self):
        d, j, label = self.fixture()
        label['anchors'] = ['not-a-grounded-id']
        with self.assertRaises(Exception):
            adapter.resolve(label, d, oldtests.S, j)

    def test_output_cap_temperature_and_original_schema_bounds_unchanged(self):
        d, j, _ = self.fixture()
        original = copy.deepcopy(oldtests.S)
        b = adapter.request_body(d, 'prompt', oldtests.S, j)
        self.assertEqual(oldtests.S, original)
        self.assertEqual(b['max_tokens'], 2048)
        self.assertEqual(b['temperature'], 0)
        self.assertEqual(b['chat_template_kwargs'], {'enable_thinking': False})
        self.assertEqual(b['response_format']['json_schema']['schema']['properties']['findings']['items']['properties']['quotes']['maxItems'], 8)


if __name__ == '__main__':
    unittest.main()
