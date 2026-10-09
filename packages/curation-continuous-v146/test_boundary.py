import unittest
from boundary import verify_reservation_pairs
class Boundary(unittest.TestCase):
 def test_record_id_not_text_sha(self):
  self.assertEqual(verify_reservation_pairs([('record1','key1','job')],[('record1','key1','job')])['records'],1)
 def test_text_sha_wrong_record_id_rejected(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('record1','key1','job')],[('textSHA','key1','job')])
 def test_crossed_pairs_not_only_sets(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('r1','k1','j'),('r2','k2','j')],[('r1','k2','j'),('r2','k1','j')])
 def test_wrong_job(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('r','k','j')],[('r','k','other')])
 def test_duplicate(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('r','k','j'),('r','k','j')],[('r','k','j')])
 def test_missing(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([],[('r','k','j')])
 def test_unknown_extra(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('r','k','j')],[])
 def test_order_independent(self):
  r=[('r1','k1','j'),('r2','k2','j')];self.assertEqual(verify_reservation_pairs(r,list(reversed(r)))['records'],2)
 def test_invalid(self):
  with self.assertRaises(ValueError):verify_reservation_pairs([('', 'k','j')],[('', 'k','j')])

from boundary import encode_boundary,decode_boundary,LIMIT
class Compression(unittest.TestCase):
 def test_full_roundtrip(self):
  x={'files_sha256':{'路径':'abc'},'body_ids':['record'],'request_keys':['key']};self.assertEqual(decode_boundary(encode_boundary(x)),x)
 def test_wrong_sha(self):
  x=encode_boundary({'a':1});x['content_sha256']='0'*64
  with self.assertRaises(ValueError):decode_boundary(x)
 def test_wrong_size(self):
  x=encode_boundary({'a':1});x['bytes']+=1
  with self.assertRaises(ValueError):decode_boundary(x)
 def test_oversized(self):
  x=encode_boundary({});x['bytes']=LIMIT+1
  with self.assertRaises(ValueError):decode_boundary(x)
 def test_invalid_base64(self):
  x=encode_boundary({});x['payload']='!'
  with self.assertRaises(ValueError):decode_boundary(x)
 def test_not_object(self):
  with self.assertRaises(ValueError):decode_boundary(encode_boundary(['a']))
 def test_unknown_envelope(self):
  x=encode_boundary({});x['unknown']=True
  with self.assertRaises(ValueError):decode_boundary(x)

import tempfile,json
from pathlib import Path
from boundary import cached_boundary
from common import sha
class Cached(unittest.TestCase):
 def case(self,change=None):
  td=tempfile.TemporaryDirectory();self.addCleanup(td.cleanup);p=Path(td.name)/'proof.json';v=dict(body_ids=['record'],request_keys=['key'],reservation_binding=dict(records=1,exact_body_key_job_binding=True,text_sha_not_used_as_record_id=True),full_physical_receipts_verified=1,ledger_counts={'job':1},no_teacher_requests=True,files_sha256={'/old/file':'a'*64},unit={'MainPID':'0'})
  if change:change(v)
  p.write_text(json.dumps(v));return dict(cached_gpu_boundary=str(p),cached_gpu_boundary_sha256=sha(p),expected_prior_requests=1,old_remote_root='/old')
 def test_full_actual_bound(self):self.assertEqual(cached_boundary(self.case())['body_ids'],['record'])
 def test_sha_changed(self):
  c=self.case();c['cached_gpu_boundary_sha256']='0'*64
  with self.assertRaises(ValueError):cached_boundary(c)
 def test_missing_record(self):
  with self.assertRaises(ValueError):cached_boundary(self.case(lambda v:v.update(body_ids=[])))
 def test_missing_exact(self):
  with self.assertRaises(ValueError):cached_boundary(self.case(lambda v:v['reservation_binding'].update(exact_body_key_job_binding=False)))
 def test_physical_missing(self):
  with self.assertRaises(ValueError):cached_boundary(self.case(lambda v:v.update(full_physical_receipts_verified=0)))
 def test_foreign_file(self):
  with self.assertRaises(ValueError):cached_boundary(self.case(lambda v:v.update(files_sha256={'/other/file':'a'*64})))
 def test_active_old(self):
  with self.assertRaises(ValueError):cached_boundary(self.case(lambda v:v['unit'].update(MainPID='5')))
