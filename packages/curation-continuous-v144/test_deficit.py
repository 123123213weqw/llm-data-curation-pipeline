import unittest,json,tempfile,sqlite3
from pathlib import Path
from deficit import next_source,validate_targets,observe_accounting
from common import sha
T={'general_en':7_000_000_000,'general_zh':5_000_000_000,'code':4_000_000_000,'technical':2_000_000_000,'math':2_000_000_000}
def source(d,n='s'):return dict(cohort=n+'/'+d+'/en',scope=n+d)
def account(**ready):return dict(targets=T,verified_ready=ready,pending_candidate_reservations={})
class Deficit(unittest.TestCase):
 def test_technical_first(self):
  self.assertEqual(next_source([source(d) for d in T],account(general_en=3990919174,general_zh=899023085,code=874696154,technical=25952215,math=2040215701),{})['cohort'],'s/technical/en')
 def test_code_before_english(self):self.assertEqual(next_source([source('code'),source('general_en')],account(code=874696154,general_en=3990919174),{})['cohort'],'s/code/en')
 def test_ratio_not_absolute_gap(self):self.assertEqual(next_source([source('technical'),source('general_en')],account(technical=2000000,general_en=3000000000),{})['cohort'],'s/technical/en')
 def test_pending_affects_order(self):
  a=account(code=100,technical=10);a['pending_candidate_reservations']={'technical':2_000_000_000}
  self.assertEqual(next_source([source('code'),source('technical')],a,{})['cohort'],'s/code/en');self.assertEqual(a['verified_ready']['technical'],10)
 def test_scopes_rotate(self):
  a,b=source('code','a'),source('code','b');self.assertEqual(next_source([a,b],account(),{a['scope']:10})['scope'],b['scope'])
 def test_empty_eligible_wait(self):self.assertIsNone(next_source([],account(),{}))
 def test_blocked_not_reintroduced(self):self.assertEqual(next_source([source('general_en')],account(),{})['cohort'],'s/general_en/en')
 def test_completed_math_not_favored(self):self.assertEqual(next_source([source('math'),source('code')],account(math=2040215701,code=874696154),{})['cohort'],'s/code/en')
 def test_all_target_filled_continue_cleaning(self):self.assertIsNotNone(next_source([source('code')],account(**T),{}))
 def test_unknown_domain_failclosed(self):
  with self.assertRaises(ValueError):next_source([source('other')],account(),{})
 def test_negative_failclosed(self):
  with self.assertRaises(ValueError):next_source([source('code')],account(code=-1),{})
 def test_float_failclosed(self):
  with self.assertRaises(ValueError):next_source([source('code')],account(code=1.2),{})
 def test_bool_failclosed(self):
  with self.assertRaises(ValueError):next_source([source('code')],account(code=True),{})
 def test_zero_target_failclosed(self):
  with self.assertRaises(ValueError):validate_targets(dict(T,code=0))
 def test_missing_target_failclosed(self):
  with self.assertRaises(ValueError):validate_targets({'code':100})
 def test_real_sql_and_pending_terminal(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'queue').mkdir();(h/'events').mkdir();recipe=h/'recipe.json';recipe.write_text(json.dumps({'targets_by_domain':T}));db=h/'s.db';c=sqlite3.connect(db);c.executescript('CREATE TABLE batches(batch_id TEXT PRIMARY KEY,domain TEXT);CREATE TABLE releases(batch_id TEXT PRIMARY KEY,train_tokens INTEGER);INSERT INTO batches VALUES("x","code");INSERT INTO releases VALUES("x",100);');c.commit();c.close()
   (h/'queue/1.json').write_text(json.dumps(dict(name='y',scope='scope',cohort='src/technical/en',candidate_train_body_tokens=200)))
   cfg=dict(supply_recipe=str(recipe),supply_recipe_sha256=sha(recipe),database=str(db));a=observe_accounting(h,cfg);self.assertEqual(a['verified_ready'],{'code':100});self.assertEqual(a['pending_candidate_reservations']['technical'],200);self.assertEqual(a['active_scopes'],['scope'])
   (h/'events/y_PUBLICATION_TERMINAL.json').write_text('{}');a=observe_accounting(h,cfg);self.assertEqual(a['pending_candidate_reservations']['technical'],0);self.assertEqual(a['active_scopes'],[])
 def test_recipe_sha_changed_failclosed(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'recipe.json';p.write_text('{}')
   with self.assertRaises(ValueError):observe_accounting(td,dict(supply_recipe=str(p),supply_recipe_sha256='0'*64))
