import unittest,tempfile,json,hashlib,copy,random,sqlite3,threading
from pathlib import Path
from common import frozen,sha
from portable import build_index,ProofIndex,make_portable,verify_portable,verify_absence,reserve_fresh,write_input_manifests,verify_cpu_input

def hx(n):return f'{n:064x}'
class PortableTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.H=Path(self.tmp.name)
  frozen(self.H/'EXCLUSION_BASE.json',{'body_ids':[hx(3),hx(7),hx(11)],'request_keys':[hx(4),hx(8),hx(12)],'unknown_keys':[hx(4)]})
  self.c=build_index(self.H,[hx(3),hx(7),hx(11)],[hx(4),hx(8),hx(12)]);self.idx=ProofIndex(self.H)
 def tearDown(self):self.idx.close();self.tmp.cleanup()
 def proof(self):return make_portable(self.H,self.idx,[hx(0),hx(5),hx(15)],[hx(1),hx(6),hx(16)])
 def test_exact_absence_lower_interior_upper(self):self.assertTrue(verify_portable(self.H,self.proof()))
 def test_existing_prior_body_rejected(self):
  with self.assertRaises(ValueError):make_portable(self.H,self.idx,[hx(3)],[hx(1)])
 def test_existing_unknown_key_rejected(self):
  with self.assertRaises(ValueError):make_portable(self.H,self.idx,[hx(2)],[hx(4)])
 def test_duplicate_body_rejected(self):
  with self.assertRaises(ValueError):make_portable(self.H,self.idx,[hx(2)]*2,[hx(1),hx(6)])
 def test_duplicate_key_rejected(self):
  with self.assertRaises(ValueError):make_portable(self.H,self.idx,[hx(1),hx(2)],[hx(6)]*2)
 def test_root_tamper_rejected(self):
  p=self.proof();p['commitment_sha256']='0'*64
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_neighbor_value_tamper_rejected(self):
  p=self.proof();p['body_absence'][1]['left']['value']=hx(1)
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_neighbor_index_tamper_rejected(self):
  p=self.proof();p['body_absence'][1]['left']['index']=1
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_missing_witness_rejected(self):
  p=self.proof();p['body_absence'].pop()
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_nonadjacent_authenticated_neighbors_rejected(self):
  w={'left':self.idx.inclusion('body',0),'right':self.idx.inclusion('body',2)}
  with self.assertRaises(ValueError):verify_absence('body',self.c['sets']['body'],hx(8),w)
 def test_wrong_boundary_rejected(self):
  with self.assertRaises(ValueError):verify_absence('body',self.c['sets']['body'],hx(0),{'left':None,'right':self.idx.inclusion('body',1)})
 def test_odd_duplicate_tamper_rejected(self):
  p=self.proof();p['body_absence'][2]['left']['siblings'][0]=hx(99)
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_body_and_key_domain_cannot_exchange(self):
  p=self.proof();p['body_absence']=p['key_absence']
  with self.assertRaises(ValueError):verify_portable(self.H,p)
 def test_full_vector_change_rejected(self):
  (self.H/'exclusion_index/body.values.bin').write_bytes(b'x'*96)
  with self.assertRaises(ValueError):ProofIndex(self.H)
 def test_invalid_value_never_truncated(self):
  with self.assertRaises(ValueError):make_portable(self.H,self.idx,['short'],[hx(1)])
 def test_persistent_reservation_no_second_attempt(self):
  name='qwen144_'+'a'*24;reserve_fresh(self.H,name,[hx(1)],[hx(2)])
  with self.assertRaises(ValueError):reserve_fresh(self.H,name,[hx(1)],[hx(2)])
 def test_cross_lane_body_conflict_preserved(self):
  reserve_fresh(self.H,'qwen144_'+'a'*24,[hx(1)],[hx(2)])
  with self.assertRaises(ValueError):reserve_fresh(self.H,'qwen144_'+'b'*24,[hx(1)],[hx(5)])
 def test_cross_lane_key_conflict_preserved(self):
  reserve_fresh(self.H,'qwen144_'+'a'*24,[hx(1)],[hx(2)])
  with self.assertRaises(ValueError):reserve_fresh(self.H,'qwen144_'+'b'*24,[hx(5)],[hx(2)])
 def test_reservation_conflict_transaction_rolls_back_whole_scope(self):
  reserve_fresh(self.H,'qwen144_'+'a'*24,[hx(1)],[hx(2)])
  with self.assertRaises(ValueError):reserve_fresh(self.H,'qwen144_'+'b'*24,[hx(3),hx(1)],[hx(4),hx(5)])
  d=sqlite3.connect(self.H/'FRESH_RESERVATIONS.sqlite');self.assertEqual(d.execute('select count(*) from requests').fetchone()[0],1);d.close()
 def test_concurrent_unique_fresh_reservations(self):
  errors=[]
  def f(i):
   try:reserve_fresh(self.H,'qwen144_'+f'{i:024x}',[hx(i+100)],[hx(i+200)])
   except Exception as e:errors.append(e)
  threads=[threading.Thread(target=f,args=(i,)) for i in range(8)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(errors,[])
 def test_CPU_full_and_GPU_review_manifests_exactly_bound(self):
  F=self.H/'payload/gpu_2/item';F.mkdir(parents=True);(F/'review').mkdir();(F/'review/full_body').write_text('all full literal body');(F/'candidates.parquet').write_text('whole candidate');(F/'ALLOCATION_INTENT.json').write_text('all candidate hashes');(F/'EXCLUSION_PROOF.json').write_text('proof')
  write_input_manifests(self.H,F);self.assertTrue(verify_cpu_input(self.H,F));g=json.loads((F/'INPUT_FILES.json').read_text());self.assertNotIn('gpu_2/item/ALLOCATION_INTENT.json',g);self.assertIn('gpu_2/item/review/full_body',g)
  (F/'ALLOCATION_INTENT.json').write_text('tampered')
  with self.assertRaises(ValueError):verify_cpu_input(self.H,F)
 def test_no_threshold_protocol_change_in_transport(self):
  p=self.proof();self.assertLess(len(json.dumps(p)),10000);self.assertNotIn('old_attempted_body_ids',p)
 def test_count_and_shape_bound(self):
  c=json.loads((self.H/'EXCLUSION_COMMITMENT.json').read_text());c['sets']['body']['count']=4;(self.H/'EXCLUSION_COMMITMENT.json').write_text(json.dumps(c))
  with self.assertRaises(ValueError):verify_portable(self.H,self.proof())
 def test_randomized_equivalence_to_original_full_set(self):
  r=random.Random(42)
  for n in [0,1,2,3,4,7,16,33,65]:
   with tempfile.TemporaryDirectory() as td:
    H=Path(td);old=set(r.sample(range(200),n));frozen(H/'EXCLUSION_BASE.json',{});c=build_index(H,map(hx,old),[]);idx=ProofIndex(H)
    try:
     for x in range(201):
      if x in old:
       with self.assertRaises(ValueError):idx.absence('body',hx(x))
      else:verify_absence('body',c['sets']['body'],hx(x),idx.absence('body',hx(x)))
    finally:idx.close()
if __name__=='__main__':unittest.main()
