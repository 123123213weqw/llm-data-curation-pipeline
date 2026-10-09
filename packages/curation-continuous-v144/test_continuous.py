import unittest,tempfile,json,threading,time,http.client
from pathlib import Path
from flow import can_prepare,backlog,event_terminal,first_ready,valid_flow_config,choose_mode,safe_scope,block,blocked
from common import frozen,sha,pressure_values,cpu_pressure_values,fresh,terminal_ok
from engine import refill
from gpu import proxy_handler,verify_files
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
class DurableFlow(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.H=Path(self.tmp.name);(self.H/'queue').mkdir();(self.H/'events').mkdir()
 def tearDown(self):self.tmp.cleanup()
 def task(self,n):frozen(self.H/'queue'/(str(n)+'.json'),dict(name='x'+str(n)))
 def test_after_first_READY_keeps_preparing(self):
  self.task(0);frozen(self.H/'events/x0_PUBLICATION_TERMINAL.json',dict(state='READY_INTERNAL'));self.assertTrue(can_prepare(self.H,4))
 def test_bounded_four_includes_CPU_publication(self):
  for i in range(4):self.task(i)
  frozen(self.H/'events/x0_IMPORTED.json',{})
  self.assertEqual(backlog(self.H),4);self.assertFalse(can_prepare(self.H,4))
 def test_ready_terminal_releases_capacity(self):
  for i in range(4):self.task(i)
  frozen(self.H/'events/x0_PUBLICATION_TERMINAL.json',{})
  self.assertTrue(can_prepare(self.H,4))
 def test_unknown_preserved_not_reissued(self):
  self.task(0);frozen(self.H/'events/x0_QA_HOLD.json',dict(no_retry=True));block(self.H,'a'*24,'unknown');self.assertTrue(blocked(self.H,'a'*24));self.assertTrue(event_terminal(self.H,'x0'))
 def test_source_QA_is_terminal_not_READY(self):
  self.task(0);frozen(self.H/'events/x0_SOURCE_TERMINAL.json',dict(not_READY=True));self.assertEqual(backlog(self.H),0)
 def test_stop_prevents_fresh_allocation(self):frozen(self.H/'STOP_NEW.json',{});self.assertFalse(can_prepare(self.H,4))
 def test_bad_unbounded_backlog(self):
  for n in (0,5,True):
   with self.assertRaises(ValueError):can_prepare(self.H,n)
 def test_unknown_feedback_cannot_start_next(self):self.assertFalse(first_ready({'name':'x'},{'name':'x','state':'HOLD_UNKNOWN'}))
 def test_wrong_batch_feedback_cannot_start_next(self):self.assertFalse(first_ready({'name':'x'},{'name':'y','state':'READY_INTERNAL'}))
 def test_verified_feedback_starts_next(self):self.assertTrue(first_ready({'name':'x'},{'name':'x','state':'READY_INTERNAL'}))
 def test_source_calibration_feedback_is_not_train_READY(self):self.assertTrue(first_ready({'name':'x'},{'name':'x','state':'SOURCE_CALIBRATED'}))
 def test_failed_source_no_bulk_but_original_individual(self):self.assertEqual(choose_mode(0,{'approved_strata':[]}), 'individual')
 def test_approved_source_keeps_original_individual_rotation(self):
  g={'approved_strata':['medium/math/en']};self.assertEqual([choose_mode(i,g) for i in range(4)],['source_audit']*3+['individual'])
 def test_unsafe_scope(self):
  with self.assertRaises(ValueError):safe_scope('../bad')
 def test_immutable_intent_cannot_be_recreated(self):
  frozen(self.H/'intent',{})
  with self.assertRaises(FileExistsError):frozen(self.H/'intent',{})
 def test_SHA_admission(self):
  (self.H/'payload').mkdir();(self.H/'payload/a').write_text('a');verify_files(self.H,{'a':sha(self.H/'payload/a')})
  with self.assertRaises(ValueError):verify_files(self.H,{'a':'0'*64})
 def test_input_path_traversal(self):
  with self.assertRaises(ValueError):verify_files(self.H,{'../a':'0'*64})
 def test_new_request_key_cannot_replay(self):
  with self.assertRaises(ValueError):fresh(['new'],['old'],[],['old'])
 def test_prior_unknown_body_isolated(self):
  with self.assertRaises(ValueError):fresh(['old'],['new'],['old'],[])
 def test_terminal_exact_coverage(self):
  with self.assertRaises(ValueError):terminal_ok(dict(stop_reason=None,selected=64,considered=63))
class ConfigGuard(unittest.TestCase):
 def cfg(self):return dict(version=144,compute_workers=4,qa_workers=8,maximum_backlog=4,no_paid=True,no_training=True,quality_thresholds_changed=False,stop_on_first_ready=False,maximum_batches=None)
 def test_continuous_no_total_batch_limit(self):self.assertTrue(valid_flow_config(self.cfg()))
 def test_old_four_batch_experiment_rejected(self):
  c=self.cfg();c['maximum_batches']=4
  with self.assertRaises(ValueError):valid_flow_config(c)
 def test_untested16_rejected(self):
  c=self.cfg();c['qa_workers']=16
  with self.assertRaises(ValueError):valid_flow_config(c)
 def test_quality_lowering_rejected(self):
  c=self.cfg();c['quality_thresholds_changed']=True
  with self.assertRaises(ValueError):valid_flow_config(c)
 def test_CPU_unused_swap_exemption_preserves_PSI(self):
  v=cpu_pressure_values(dict(reasons=['SwapFree','PSI'],mem_available=144*1024**3));self.assertEqual(v['reasons'],['PSI'])
 def test_GPU_original_swap_guard(self):
  v=pressure_values(dict(MemAvailable=144*1024**3,SwapTotal=4*1024**3,SwapFree=0),{'some':0,'full':0},0,0);self.assertIn('SwapFree',v['reasons'])
 def test_CPU_headroom64(self):self.assertTrue(cpu_pressure_values(dict(reasons=[],mem_available=63*1024**3))['reasons'])
class Refill(unittest.TestCase):
 def test_completion_no_group_barrier(self):
  starts={};ends={}
  def work(x):starts[x]=time.monotonic();time.sleep(.1 if x==0 else .01);ends[x]=time.monotonic();return x
  r=refill(range(5),lambda x:x,work,lambda a,b:True,2);self.assertLess(starts[2],ends[0]);self.assertEqual(r['completed'],5)
 def test_unknown_drains_without_new_reserve(self):
  started=[];finished=[]
  def work(x):time.sleep(.01 if x==0 else .08);return x
  def prep(x):started.append(x);return x
  def finish(a,b):finished.append(a);return a!=0
  r=refill(range(20),prep,work,finish,2);self.assertEqual(started,[0,1]);self.assertEqual(set(finished),{0,1});self.assertIsNotNone(r['stop_reason'])
 def test_pressure_defer_no_send(self):
  with self.assertRaises(TimeoutError):refill([1],lambda x:self.fail(),lambda x:x,lambda a,b:True,1,lambda:False,idle_limit=.01)
 def test_deferred_then_resumed_same_single_reservation(self):
  n=[0];calls=[]
  def admit():n[0]+=1;return n[0]>2
  r=refill([1],lambda x:calls.append(x) or x,lambda x:x,lambda a,b:True,1,admit);self.assertEqual(calls,[1]);self.assertEqual(r['completed'],1)
class TransparentAliases(unittest.TestCase):
 def test_exact_raw_body_and_one_backend_POST(self):
  calls=[]
  class Echo(BaseHTTPRequestHandler):
   def do_POST(s):
    raw=s.rfile.read(int(s.headers['Content-Length']));calls.append(raw);s.send_response(200);s.send_header('Content-Length',str(len(raw)));s.end_headers();s.wfile.write(raw)
   def log_message(*a):pass
  backend=ThreadingHTTPServer(('127.0.0.1',0),Echo);proxy=ThreadingHTTPServer(('127.0.0.1',0),proxy_handler(backend.server_port))
  for server in (backend,proxy):threading.Thread(target=server.serve_forever,daemon=True).start()
  try:
   raw=b'{"unicode":"\\u4e2d", "full":"not truncated"}';c=http.client.HTTPConnection('127.0.0.1',proxy.server_port);c.request('POST','/v1/chat/completions',raw,{'Content-Type':'application/json'});r=c.getresponse();self.assertEqual(r.status,200);self.assertEqual(r.read(),raw);self.assertEqual(calls,[raw]);c.close()
  finally:
   for server in (proxy,backend):server.shutdown();server.server_close()
 def test_no_unknown_path_proxy(self):
  proxy=ThreadingHTTPServer(('127.0.0.1',0),proxy_handler(1));threading.Thread(target=proxy.serve_forever,daemon=True).start()
  try:
   c=http.client.HTTPConnection('127.0.0.1',proxy.server_port);c.request('GET','/reset_prefix_cache');r=c.getresponse();self.assertEqual(r.status,404);r.read();c.close()
  finally:proxy.shutdown();proxy.server_close()

class FreshSelection(unittest.TestCase):
 def setUp(self):
  import sqlite3
  self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
  self.db.executescript('CREATE TABLE files(id INTEGER PRIMARY KEY,source TEXT); INSERT INTO files VALUES(1,"A"),(2,"B");CREATE TABLE records(h TEXT PRIMARY KEY,fid INTEGER,domain TEXT,lang TEXT,gate TEXT,job TEXT,stratum TEXT,split TEXT,rank INTEGER,n INTEGER);CREATE INDEX records_source_v15 ON records(fid,domain,lang);')
  self.cfg={'maximum_batch_documents':16,'batch_train_body_tokens':2};self.perf={'fast_batch_size_multiplier':4,'heldout_target_tokens_per_stratum':2};self.sg={'approved_strata':['s']}
  for fid,source in [(1,'A'),(2,'B')]:
   for split in ('train','validation','test'):
    for rank in range(3):self.db.execute('INSERT INTO records VALUES(?,?,?,?,?,?,?,?,?,?)',(source+split+str(rank),fid,'d','en','CANDIDATE',None,'s',split,rank,3))
 def tearDown(self):self.db.close()
 def select(self,source='A',mode='source_audit',sg=None):
  from selection import select_fresh
  return select_fresh(self.db,self.cfg,source,'d','en',sg or self.sg,mode,self.perf)
 def test_excluded_first_heldout_refilled_before_LIMIT(self):
  from selection import bind_exclusions,route_complete
  bind_exclusions(self.db,['Avalidation0','Atest0','Atrain0']);rows=self.select()
  self.assertTrue(route_complete(rows,self.sg,'source_audit'));self.assertEqual({r['h'] for r in rows},{'Avalidation1','Atest1','Atrain1','Atrain2'})
 def test_empty_exclusion_byte_equivalent_original_selector(self):
  from selection import bind_exclusions
  from p0_qwen_overnight_slot_v67 import select_new
  bind_exclusions(self.db,[])
  self.assertEqual([dict(r) for r in self.select()],[dict(r) for r in select_new(self.db,self.cfg,'A','d','en',self.sg,'source_audit',self.perf)])
 def test_one_source_shortage_other_source_continues(self):
  from selection import bind_exclusions,route_complete
  bind_exclusions(self.db,['Atest'+str(i) for i in range(3)])
  self.assertEqual(self.select(),[]);self.assertTrue(route_complete(self.select('B'),self.sg,'source_audit'))
 def test_individual_excludes_original_heldout_not_train_only(self):
  from selection import bind_exclusions,route_complete
  bind_exclusions(self.db,['Atest0','Avalidation0'])
  rows=self.select(mode='individual',sg={'approved_strata':[]});self.assertTrue(route_complete(rows,{},'individual'));self.assertFalse({'Atest0','Avalidation0'}&{r['h'] for r in rows})
 def test_invalid_metadata_fails_global_not_shortage(self):
  from selection import bind_exclusions
  bind_exclusions(self.db,[]);self.db.execute("UPDATE records SET n=0 WHERE h='Atest0'")
  with self.assertRaises(ValueError):self.select()
 def test_missing_split_route_local_only(self):
  from selection import route_complete
  self.assertFalse(route_complete([dict(split=x,stratum='s') for x in ('train','validation')],{'approved_strata':['s']},'source_audit'))
 def test_source_sample_excludes_before_rank_with_full_population(self):
  from selection import bind_exclusions,fresh_clause
  from p0_inventory_supply_v24 import sample
  bind_exclusions(self.db,['Atrain0']);rows,pop=sample(self.db,'A','d','en',2,gate_clause=fresh_clause("r.gate='CANDIDATE' AND r.job IS NULL"));self.assertEqual(pop,{'s':2});self.assertEqual([r['h'] for r in rows],['Atrain1','Atrain2'])
 def test_unknown_route_mode_not_swallowed(self):
  from selection import bind_exclusions
  bind_exclusions(self.db,[])
  with self.assertRaises(ValueError):self.select(mode='unknown')

if __name__=='__main__':unittest.main()
