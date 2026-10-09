import copy,json,tempfile,unittest
from pathlib import Path
from parallel_guard import admissible_block,REASON,verify_guard
from common import frozen,sha
class Parallel(unittest.TestCase):
 def fixtures(self):
  b={'reason':REASON,'no_retry':True};g={'status':'passed','holds':[],'counts':dict(keep_total=16,keep_valid=16,keep_keep=16,drop_total=16,drop_valid=16,drop_keep=0)};c={'status':'passed','gate':copy.deepcopy(g),'model_calls':0,'no_unknown_reissued':True};return b,g,c
 def test_exact_complete_cache_is_accepted(self):self.assertTrue(admissible_block(*self.fixtures()))
 def test_unknown_not_admissible(self):
  b,g,c=self.fixtures();b['reason']='Unknown local response retained; no replay'
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def test_quality_hold_not_admissible(self):
  b,g,c=self.fixtures();g['status']='hold'
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def test_source_scope_not_cross_borrowed(self):
  b,g,c=self.fixtures();c['gate']['scope']='other'
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def test_partial_controls_rejected(self):
  b,g,c=self.fixtures();g['counts']['keep_valid']=15;c['gate']=g
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def test_teacher_replay_disallowed(self):
  b,g,c=self.fixtures();c['model_calls']=32
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def test_unknown_receipt_excluded(self):
  b,g,c=self.fixtures();c['no_unknown_reissued']=False
  with self.assertRaises(ValueError):admissible_block(b,g,c)
 def guard(self,H):
  p=H/'prior';p.write_text('immutable prior block');frozen(H/'SOURCE_CATALOG.json',[{'cohort':'finewiki_zh_2025_candidate_v1/general_zh/zh','logical':4}]);frozen(H/'PARALLEL_SCOPE_BOUNDARY.json',{'prior_immutable_files':{str(p):sha(p)},'all_prior_gpu0_routes_blocked':True,'prior_unknowns_preserved':True,'stock_body_primary_key':True});return p
 def test_guard_accepts_distinct_one_source(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);self.guard(H);self.assertTrue(verify_guard(H,{}))
 def test_old_block_mutation_fails_closed(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);p=self.guard(H);p.write_text('cleared')
   with self.assertRaises(ValueError):verify_guard(H,{})
 def test_competing_lane_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);self.guard(H);(H/'SOURCE_CATALOG.json').write_text('[{"cohort":"finewiki_zh_2025_candidate_v1/general_zh/zh","logical":3}]')
   with self.assertRaises(ValueError):verify_guard(H,{})
 def test_missing_stock_freshness_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);self.guard(H);p=H/'PARALLEL_SCOPE_BOUNDARY.json';g=json.loads(p.read_text());g['stock_body_primary_key']=False;p.write_text(json.dumps(g))
   with self.assertRaises(ValueError):verify_guard(H,{})

class StockSchema(unittest.TestCase):
 def fixture(self):
  import sqlite3
  d=sqlite3.connect(':memory:');d.executescript("CREATE TABLE files(id INTEGER PRIMARY KEY,source TEXT);CREATE TABLE records(h TEXT PRIMARY KEY,fid INTEGER,domain TEXT,lang TEXT,gate TEXT,job TEXT);INSERT INTO files VALUES(1,'code_source'),(2,'finewiki_zh_2025_candidate_v1');INSERT INTO records VALUES('code',1,'code','python','CANDIDATE',NULL),('code_fallback',1,'code','python','CANDIDATE_FALLBACK',NULL),('otherlang',1,'code','java','CANDIDATE',NULL),('hold',1,'code','python','HOLD',NULL),('zh',2,'general_zh','zh','CANDIDATE',NULL);");return d
 def test_exact_original_join_schema_not_invented_source_column(self):
  from parallel_guard import competing_stock
  d=self.fixture()
  try:self.assertEqual(set(competing_stock(d,['code_source/code/python'])),{'code','code_fallback'})
  finally:d.close()
 def test_no_cross_source_or_language_exclusion(self):
  from parallel_guard import competing_stock
  d=self.fixture()
  try:self.assertEqual(list(competing_stock(d,['code_source/code/java'])),['otherlang'])
  finally:d.close()
