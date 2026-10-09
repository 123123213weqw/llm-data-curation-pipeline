import unittest,tempfile,json,sys,time,os
from pathlib import Path
from common import frozen,sha
from flow import event_terminal,backlog,block,hard
from transport import dispatch_once,feedback_once,notify_done_once
from unittest.mock import patch
import receipt_adapter

class TransportTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.H=Path(self.tmp.name)
  for n in ('events','payload/gpu_2/qwen144_'+'a'*24+'/review','queue'): (self.H/n).mkdir(parents=True)
  self.F=next((self.H/'payload/gpu_2').iterdir());(self.F/'INPUT_FILES.json').write_text('{}');(self.F/'full_body').write_text('all original documents unchanged');(self.F/'RELEASE_CONFIG.json').write_text('{}')
  self.t=dict(name=self.F.name,folder=str((self.F/'review').relative_to(self.H/'payload')),scope='b'*24,config=str(self.F/'RELEASE_CONFIG.json'),kind='batch')
  frozen(self.H/'queue/0.json',self.t);self.calls=[];self.states=[]
 def tearDown(self):self.tmp.cleanup()
 def mark(self,q,t,state):self.states.append(state)
 def failure(self,error):
  def transfer(*a):
   self.calls.append('one');frozen(self.H/'events'/(self.t['name']+'_TRANSFER_INTENT.json'),{});raise error
  return transfer
 def test_timeout_does_not_stop_independent_sources(self):
  before=sha(self.F/'full_body');self.assertFalse(dispatch_once(self.H,None,self.t,self.failure(TimeoutError('lost')),self.mark))
  self.assertEqual(self.states,['HOLD_TRANSPORT_UNKNOWN']);self.assertEqual(before,sha(self.F/'full_body'));self.assertTrue(event_terminal(self.H,self.t['name']));self.assertEqual(backlog(self.H),0);self.assertFalse((self.H/'STOP_NEW.json').exists())
  other=dict(self.t,name='qwen144_'+'c'*24,scope='d'*24)
  self.assertTrue(dispatch_once(self.H,None,other,lambda *a:self.calls.append('other'),self.mark));self.assertEqual(self.calls,['one','other'])
 def test_durable_unknown_not_resent(self):
  send=self.failure(ConnectionError('lost'));dispatch_once(self.H,None,self.t,send,self.mark)
  self.assertFalse(dispatch_once(self.H,None,self.t,send,self.mark));self.assertEqual(self.calls,['one']);self.assertEqual(len(self.states),1)
 def test_existing_intent_no_retry(self):
  frozen(self.H/'events'/(self.t['name']+'_TRANSFER_INTENT.json'),{})
  with self.assertRaises(ValueError):dispatch_once(self.H,None,self.t,lambda *a:self.fail(),self.mark)
 def test_other_errors_remain_failclosed(self):
  with self.assertRaises(ValueError):dispatch_once(self.H,None,self.t,self.failure(ValueError('SHA mismatch')),self.mark)
  self.assertFalse(event_terminal(self.H,self.t['name']));self.assertEqual(self.states,[])
 def test_queued_blocked_scope_never_sent(self):
  block(self.H,self.t['scope'],'unknown');self.assertFalse(dispatch_once(self.H,None,self.t,lambda *a:self.fail(),self.mark));self.assertEqual(self.states,['HOLD_TRANSPORT_NOT_SENT'])
 def test_calibration_unknown_is_preserved_no_stock_change(self):
  t=dict(self.t,kind='source');self.assertFalse(dispatch_once(self.H,None,t,self.failure(TimeoutError()),self.mark));self.assertEqual(self.states,[])
 def test_lost_ack_possible_remote_accepted_no_replay(self):
  accepted=[]
  def send(*a):accepted.append(self.t['name']);raise ConnectionError('ack lost after admission')
  dispatch_once(self.H,None,self.t,send,self.mark);dispatch_once(self.H,None,self.t,send,self.mark);self.assertEqual(accepted,[self.t['name']])
 def test_feedback_loss_retains_local_READY(self):
  p=self.H/'events'/(self.t['name']+'_VERIFIED_READY.json');frozen(p,{'train_body_tokens':100});h=sha(p)
  def send(*a):self.calls.append('feedback');frozen(self.H/'events'/(self.t['name']+'_FEEDBACK_INTENT.json'),{});raise TimeoutError()
  self.assertFalse(feedback_once(self.H,{},self.t,'READY_INTERNAL',send));self.assertFalse(feedback_once(self.H,{},self.t,'READY_INTERNAL',send));self.assertEqual(sha(p),h);self.assertEqual(self.calls,['feedback']);self.assertFalse((self.H/'STOP_NEW.json').exists())
 def test_feedback_bad_identity_not_swallowed(self):
  def send(*a):raise ValueError('wrong scope')
  with self.assertRaises(ValueError):feedback_once(self.H,{},self.t,'READY_INTERNAL',send)
 def test_done_lost_ack_once(self):
  frozen(self.H/'PRODUCER_DONE.json',{})
  def send():self.calls.append('done');raise TimeoutError()
  self.assertIsNone(notify_done_once(self.H,send))
  with self.assertRaises(ValueError):notify_done_once(self.H,send)
  self.assertEqual(self.calls,['done'])
 def test_hard_real_child_timeout_no_retry(self):
  started=time.monotonic()
  with self.assertRaises(TimeoutError):hard([sys.executable,'-c','import time;time.sleep(20)'],timeout=.05)
  self.assertLess(time.monotonic()-started,3)
 def test_new_receipt_only_exact_old_whitelist(self):
  old=dict(self.t,name='qwen135_'+'e'*24,recovery=True,folder='gpu_2/qwen135_'+'e'*24+'/review')
  plan={'item':old,'original_item':dict(old)}
  with patch.object(receipt_adapter.Path,'read_text',return_value=json.dumps(plan)):
   receipt_adapter.safe_item(old)
   with self.assertRaises(ValueError):receipt_adapter.safe_item(dict(old,name='qwen135_'+'f'*24))
 def test_recovery_stock_expected_v135(self):
  from primary import stock_terminal
  import inspect
  self.assertIn("CPU_PREHEATED_V135_NOT_READY",inspect.getsource(stock_terminal));self.assertIn("CPU_PREHEATED_V144_NOT_READY",inspect.getsource(stock_terminal))
if __name__=='__main__':unittest.main()
