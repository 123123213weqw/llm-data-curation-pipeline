"""Offline mocks only: never independent quality approval or live GPU requests."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT/'tests')]
from small_agent.curation import evidence_ids_qwen_v25 as adapter,store_qwen_v25 as store
from small_agent.curation.core import canonical
import p0_qwen_worker_v25 as worker
import test_evidence_ids_v8 as oldtests


def judge():
    return dict(family='qwen',model='fixture-qwen',model_revision='offline-fixture-only',served_models=['fixture-qwen'],
        generation=dict(temperature=0,max_tokens=2048,response_format='json_schema',thinking='omit',
                        require_document_id_match=True,chat_template_kwargs={'enable_thinking':False},
                        evidence_id_transport=adapter.extension(),decoder_schema_projection='omit_uniqueItems_v1'),
        endpoint=dict(kind='chat',base_url='http://127.0.0.1:18000/v1',maximum_context_tokens=4096,
                      teacher_tokenizer_directory='/fixture-not-real',teacher_tokenizer_files={}))


class QwenAdapterTests(oldtests.ConservativeAdapterTests):
    def setUp(self):
        for name in ('spans','resolve','extension','wire_schema','request_body','validate_receipt'):
            p=patch.object(oldtests,name,getattr(adapter,name));p.start();self.addCleanup(p.stop)

    def fixture(self):
        doc,_,annotation=super().fixture()
        return doc,judge(),annotation

    def test_actual_chat_schema_and_full_payload_are_bound(self):
        doc,j,_=self.fixture();body=adapter.request_body(doc,'prompt',oldtests.S,j)
        self.assertEqual(body['model'],'fixture-qwen')
        self.assertEqual(body['chat_template_kwargs'],{'enable_thinking':False})
        self.assertNotIn('thinking',body);self.assertNotIn('instructions',body)
        payload=json.loads(body['messages'][1]['content'])
        self.assertEqual(payload['document_text'],doc['document_text'])
        p=store.protocol(doc,'prompt',oldtests.S,j)
        self.assertEqual(p['wire_schema_sha256'],adapter.fingerprint(body['response_format']['json_schema']['schema']))

    def test_deepseek_identity_cannot_be_relabelled(self):
        doc,j,_=self.fixture()
        for field,value in [('family','deepseek')]:
            bad=copy.deepcopy(j);bad[field]=value
            with self.assertRaises(ValueError):adapter.request_body(doc,'p',oldtests.S,bad)
        j['endpoint']['kind']='responses'
        with self.assertRaises(ValueError):adapter.request_body(doc,'p',oldtests.S,j)


class LocalWorkerTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup);self.root=Path(t.name)
        self.doc,_,self.wire=oldtests.EvidenceIDTests().fixture()
        self.j=judge()
        self.policy=json.loads((ROOT/'configs/curation/p0_qwen_source_audit_policy_v25.json').read_text())
        for name,value in [('policy.json',self.policy),('schema.json',oldtests.S),
                           ('judges.json',dict(version=3,deployment_status='verified',judges={'qwen':self.j}))]:
            (self.root/name).write_text(json.dumps(value))
        (self.root/'prompt.txt').write_text('Offline fixture prompt, not production.')
        (self.root/'input.jsonl').write_text(canonical(self.doc)+'\n')

    def batch(self,name):
        path=self.root/name
        store.prepare(self.root/'input.jsonl',path,self.root/'policy.json',self.root/'schema.json',self.root/'prompt.txt',self.root/'judges.json')
        b=store.Batch(path);self.addCleanup(b.close);return b

    def response(self):
        return dict(model='fixture-qwen',id='fixture-response',usage=dict(prompt_tokens=10,completion_tokens=10),
                    choices=[dict(finish_reason='stop',message=dict(content=json.dumps(self.wire)))])

    def run_mock(self,batch,*,response=None,tokens=1,error=None):
        with patch.object(worker.transport,'tokenizer_for',return_value=object()),\
             patch.object(worker.transport,'teacher_input_length',return_value=tokens),\
             patch.object(worker.transport,'send',return_value=response or self.response(),side_effect=error) as send:
            result=worker.run(batch,self.root/'local.sqlite',workers=1)
            return result,send.call_count

    def test_protocol_cache_cross_batch_never_resends_or_exports_training(self):
        a=self.batch('a');result,n=self.run_mock(a)
        self.assertEqual(n,1);self.assertEqual(result['counts']['valid_outputs'],1)
        self.assertEqual(result['batch']['status_documents'],{'audit_keep_signal':1})
        self.assertEqual(result['paid_api_requests'],0);self.assertFalse(result['training_approved'])
        with self.assertRaises(ValueError):a.export(self.root/'eligible')
        b=self.batch('b');result,n=self.run_mock(b)
        self.assertEqual(n,0);self.assertEqual(result['counts']['reused_without_request'],1)
        self.assertEqual(b.report()['job_statuses'],{'valid':1})

    def test_context_overflow_preserves_body_and_never_sends(self):
        b=self.batch('a');text=b.docs[self.doc['document_id']]['document_text']
        result,n=self.run_mock(b,tokens=10000)
        self.assertEqual(n,0);self.assertEqual(result['counts']['context_hold_no_truncation_no_request'],1)
        self.assertEqual(b.docs[self.doc['document_id']]['document_text'],text)
        self.assertEqual(b.report()['job_statuses'],{'queued':1})

    def test_unknown_transport_stops_campaign_without_resending(self):
        b=self.batch('a');result,n=self.run_mock(b,error=TimeoutError())
        self.assertEqual(n,1);self.assertEqual(result['stop_reason'],'unknown_local_response_no_auto_retry')
        with self.assertRaisesRegex(ValueError,'Unknown prior'):
            self.run_mock(b)

    def test_known_invalid_is_not_retried(self):
        b=self.batch('a');self.wire.pop('quality')
        result,n=self.run_mock(b)
        self.assertEqual(n,1);self.assertEqual(result['counts']['known_invalid_not_retried'],1)
        result,n=self.run_mock(b)
        self.assertEqual(n,0);self.assertEqual(b.report()['job_statuses'],{'invalid':1})

    def test_legacy_store_and_model_identity_are_separate(self):
        from small_agent.curation import store_v8
        reg=json.loads((self.root/'judges.json').read_text())
        with self.assertRaises(ValueError):store_v8.validate_config(self.policy,reg)
        old=copy.deepcopy(self.policy);old['review_purpose']='source_quality_audit'
        with self.assertRaises(ValueError):store.validate_config(old,reg)
        reg['judges']['deepseek']=reg['judges'].pop('qwen')
        with self.assertRaises(ValueError):store.validate_config(self.policy,reg)

    def test_original_thresholds_are_not_lowered(self):
        old=json.loads((ROOT/'configs/curation/p0_source_audit_policy_parallel_v5.json').read_text())
        for k in ('minimum_confidence','minimum_scores','maximum_batch_documents','required_release_checks','review_mode','unresolved_risk'):
            self.assertEqual(old[k],self.policy[k])
        for url in ('https://api.deepseek.com/v1','http://localhost:18000/v1','http://127.0.0.1:18000/v1?x=1'):
            j=copy.deepcopy(self.j);j['endpoint']['base_url']=url
            with self.assertRaises(ValueError):worker.local_endpoint(j)

    def test_offline_fixture_identity_cannot_call_a_live_service(self):
        registry=json.loads((self.root/'judges.json').read_text())
        registry['deployment_status']='offline_test_only'
        (self.root/'judges.json').write_text(json.dumps(registry))
        b=self.batch('a')
        with patch.object(worker.transport,'send') as send:
            with self.assertRaisesRegex(ValueError,'Offline identities'):
                worker.run(b,self.root/'local.sqlite')
            send.assert_not_called()

    def test_local_worker_cannot_reset_a_paid_ledger(self):
        from small_agent.curation.ledger import Ledger
        paid=Ledger(self.root/'local.sqlite',budget_cny=1000,account_sha256='a'*64,
                    pricing=dict(uncached_input=2,output=8,margin=1.15))
        paid.reserve('paid_request',10);paid.close()
        b=self.batch('a')
        with self.assertRaisesRegex(ValueError,'campaign budget/account/pricing changed'):
            self.run_mock(b)
        import sqlite3
        with sqlite3.connect(self.root/'local.sqlite') as db:
            self.assertEqual(db.execute('SELECT counted FROM requests WHERE job_key=?',('paid_request',)).fetchone()[0],10000000)


if __name__=='__main__':unittest.main()
