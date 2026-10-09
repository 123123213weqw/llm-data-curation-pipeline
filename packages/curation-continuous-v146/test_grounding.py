import hashlib,tempfile,unittest,sqlite3
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager
from grounding import protocol_plan,GroundingHold,record_grounding_hold

def doc(text):
 h=hashlib.sha256(text.encode()).hexdigest()
 return dict(document_id=h,body_sha256=h,document_text=text)
def batch(ds):return SimpleNamespace(docs={d['document_id']:d for d in ds},prompt='p',schema={},registry={'judges':{'qwen':{}}})
class GroundingTests(unittest.TestCase):
 def plan(self,b,fn):return protocol_plan(b,lambda d,*args:d['body_sha256'],lambda p:p,fn)
 def no_evidence(self,d):raise ValueError('No uniquely grounded evidence; hold without API')
 def test_real_original_repeated_text_holds(self):
  b=batch([doc('aaaaaaaa'*90)])
  with self.assertRaises(GroundingHold):protocol_plan(b,lambda *x:self.fail(),lambda *x:self.fail())
 def test_real_original_unique_text_unchanged_protocol(self):
  d=doc('This is an independently unique paragraph providing enough literal evidence to identify a quote.')
  self.assertEqual(protocol_plan(batch([d]),lambda d,*a:'same',lambda v:v),([d['document_id']],['same']))
 def test_full_scope_held_no_partial_keys_emitted(self):
  b=batch([doc('a'),doc('b')])
  def fn(d):
   if d['document_text']=='b':self.no_evidence(d)
   return []
  with self.assertRaises(GroundingHold) as e:self.plan(b,fn)
  self.assertEqual(len(e.exception.documents),1)
 def test_other_ValueError_not_swallowed(self):
  def fn(d):raise ValueError('Wrong model identity')
  with self.assertRaises(ValueError):self.plan(batch([doc('a')]),fn)
 def test_subclass_ValueError_not_swallowed(self):
  class Other(ValueError):pass
  def fn(d):raise Other('No uniquely grounded evidence; hold without API')
  with self.assertRaises(Other):self.plan(batch([doc('a')]),fn)
 def test_corrupt_body_not_grounding_hold(self):
  d=doc('a');d['body_sha256']='0'*64
  with self.assertRaises(ValueError):self.plan(batch([d]),self.no_evidence)
 def test_protocol_error_not_grounding_hold(self):
  def protocol(*args):raise ValueError('No uniquely grounded evidence; hold without API')
  with self.assertRaises(ValueError):protocol_plan(batch([doc('a')]),protocol,str,lambda d:[])
 def test_other_source_can_plan_after_local_hold(self):
  with self.assertRaises(GroundingHold):self.plan(batch([doc('a')]),self.no_evidence)
  self.assertEqual(len(self.plan(batch([doc('b')]),lambda d:[])[0]),1)
 def test_record_preserves_entire_allocation_not_only_bad(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);F=H/'candidate';F.mkdir();(F/'full.txt').write_text('unchanged');(H/'events').mkdir()
   db=sqlite3.connect(':memory:');db.executescript("create table jobs(name,state);create table records(h,job,gate);insert into jobs values('job','PREPARING_V146');insert into records values('a','job','CANDIDATE'),('b','job','CANDIDATE');")
   @contextmanager
   def lock(path):yield
   record_grounding_hold(H,F,H,db,'job','batch','a'*24,'src/d/en',[{'h':'a'},{'h':'b'}],GroundingHold([{'document_id':'a'}]),lock)
   self.assertEqual(db.execute('select state from jobs').fetchone()[0],'HOLD_GROUNDING_NOT_SENT')
   self.assertEqual(db.execute('select count(*) from records where gate=?',('HOLD_GROUNDING_NOT_SENT',)).fetchone()[0],2)
   self.assertEqual((F/'full.txt').read_text(),'unchanged');self.assertFalse((H/'queue').exists())
   with self.assertRaises(FileExistsError):record_grounding_hold(H,F,H,db,'job','batch','a'*24,'src/d/en',[],GroundingHold([]),lock)
   db.close()
 def test_preheated_or_worker_intent_never_reclassified(self):
  with tempfile.TemporaryDirectory() as td:
   H=Path(td);F=H/'candidate';F.mkdir();(F/'PREHEATED.json').write_text('{}')
   with self.assertRaises(ValueError):record_grounding_hold(H,F,H,None,'job','batch','a'*24,'src',[],GroundingHold([]),None)
if __name__=='__main__':unittest.main()
