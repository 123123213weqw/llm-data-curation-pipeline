import json,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
from p0_qwen_overnight_slot_v67 import observe_worker_terminal,completed_evidence_base

class TerminalRaceTests(unittest.TestCase):
 def valid(self):return json.dumps(dict(selected=32,considered=32,stop_reason=None,counts=dict(reused_without_request=32)))
 def test_cached_completion_between_probe_and_inactive_is_observed(self):
  with patch('p0_qwen_overnight_slot_v67.command',side_effect=['','inactive',self.valid()]) as command:
   self.assertEqual(observe_worker_terminal(Path('/terminal'),'u.service')['considered'],32)
   self.assertEqual(command.call_count,3)
   self.assertFalse(any('systemd-run' in str(c) for c in command.call_args_list))
 def test_recheck_still_missing_fails_closed(self):
  with patch('p0_qwen_overnight_slot_v67.command',side_effect=['','failed','']):
   with self.assertRaisesRegex(ValueError,'final recheck'):observe_worker_terminal(Path('/terminal'),'u')
 def test_recheck_unknown_stays_unknown(self):
  raw=json.dumps(dict(selected=32,considered=31,stop_reason='unknown_request'))
  with patch('p0_qwen_overnight_slot_v67.command',side_effect=['','failed',raw]):
   with self.assertRaisesRegex(ValueError,'Unknown local terminal'):observe_worker_terminal(Path('/terminal'),'u')
 def test_terminal_immediately_complete_does_not_probe_unit(self):
  with patch('p0_qwen_overnight_slot_v67.command',return_value=self.valid()) as command:
   observe_worker_terminal(Path('/terminal'),'u');self.assertEqual(command.call_count,1)
 def test_active_observation_does_not_retry_request(self):
  with patch('p0_qwen_overnight_slot_v67.command',side_effect=['','active',self.valid()]) as command,patch('p0_qwen_overnight_slot_v67.time.sleep') as sleep:
   observe_worker_terminal(Path('/terminal'),'u');sleep.assert_called_once_with(20);self.assertEqual(command.call_count,3)
 def test_transport_failure_stays_unknown(self):
  with patch('p0_qwen_overnight_slot_v67.command',side_effect=TimeoutError('SSH unknown')):
   with self.assertRaises(TimeoutError):observe_worker_terminal(Path('/terminal'),'u')

if __name__=='__main__':unittest.main()

class EvidenceLookupTests(unittest.TestCase):
 def test_cohort_bound_v39_preferred_only_when_both_gates_exist(self):
  from small_agent.curation.supply_control import digest
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);c='github/code/python';k='scope';b=r/'qwen_pool_v39/gpu_3'/digest([c])[:24]
   ref=b/'references/code_python/ACTUAL_GATE_V36.json';ref.parent.mkdir(parents=True);ref.write_text('{}')
   self.assertEqual(completed_evidence_base(r,3,c,k,'code','python'),r/'qwen_pool_v36/gpu_3')
   src=b/'source_audits'/k/'ACTUAL_GATE_V36.json';src.parent.mkdir(parents=True);src.write_text('{}')
   self.assertEqual(completed_evidence_base(r,3,c,k,'code','python'),b)
   self.assertEqual(completed_evidence_base(r,3,'other/code/python',k,'code','python'),r/'qwen_pool_v36/gpu_3')

class LongQueueWaitTests(unittest.TestCase):
 def test_long_wait_does_not_steal_existing_writer(self):
  from p0_qwen_overnight_slot_v67 import publish
  with tempfile.TemporaryDirectory() as d:
   recipe=Path(d)/'recipe.json';recipe.write_text('{"maximum_unreleased_batches":2}')
   with patch('p0_qwen_overnight_slot_v67.locked',side_effect=RuntimeError('observed_existing_lock')) as lock:
    with self.assertRaises(RuntimeError):publish(dict(root='/root',recipe=str(recipe)),None,None,None,None,'math','individual',None,None)
    self.assertEqual(lock.call_args.args[0],Path('/root/release-coordinator.lock'));self.assertTrue(43190<lock.call_args.kwargs['seconds']<=43200)

class V37EvidenceLookupTests(unittest.TestCase):
 def test_completed_v37_exact_cohort_only(self):
  from small_agent.curation.supply_control import digest
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);c='source/math/en';k='bound_scope';b=r/'qwen_pool_v37/gpu_4'/digest([c])[:24]
   ref=b/'references/math_en/ACTUAL_GATE_V36.json';ref.parent.mkdir(parents=True);ref.write_text('{}')
   self.assertEqual(completed_evidence_base(r,4,c,k,'math','en'),r/'qwen_pool_v36/gpu_4')
   src=b/'source_audits'/k/'ACTUAL_GATE_V36.json';src.parent.mkdir(parents=True);src.write_text('{}')
   self.assertEqual(completed_evidence_base(r,4,c,k,'math','en'),b)
   self.assertEqual(completed_evidence_base(r,6,c,k,'math','en'),r/'qwen_pool_v36/gpu_6')
   self.assertEqual(completed_evidence_base(r,4,'other/math/en',k,'math','en'),r/'qwen_pool_v36/gpu_4')

class ExtendedEvidence(unittest.TestCase):
 def test_actual_42_exact_cohort(self):
  from small_agent.curation.supply_control import digest
  with tempfile.TemporaryDirectory() as d:
   r=Path(d);c='source/math/en';k='scope';b=r/'qwen_pool_v42/gpu_3'/digest([c])[:24]
   for p in (b/'references/math_en/ACTUAL_GATE_V36.json',b/'source_audits'/k/'ACTUAL_GATE_V36.json'):p.parent.mkdir(parents=True,exist_ok=True);p.write_text('{}')
   self.assertEqual(completed_evidence_base(r,3,c,k,'math','en'),b)
   self.assertEqual(completed_evidence_base(r,4,c,k,'math','en'),r/'qwen_pool_v36/gpu_4')

class CapacityWaitTests(unittest.TestCase):
 def test_original_cap_counts_waiting_gate_not_ready_or_quarantined(self):
  import sqlite3
  from p0_qwen_overnight_slot_v67 import capacity_available
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'db';db=sqlite3.connect(p);db.execute('create table batches(status text)');db.executemany('insert into batches values(?)',[(x,) for x in ['waiting_gate','ready','quarantined','legacy_internal']]);db.commit()
   self.assertEqual(capacity_available(p,dict(maximum_unreleased_batches=2)),(True,1));db.execute("insert into batches values('waiting_gate')");db.commit();self.assertEqual(capacity_available(p,dict(maximum_unreleased_batches=2)),(False,2));db.close()
 def test_capacity_wait_releases_writer_lock_before_sleep_and_calls_once(self):
  from contextlib import contextmanager
  import p0_qwen_overnight_slot_v67 as m
  held=[]
  @contextmanager
  def lock(*a,**k):
   held.append(True)
   try:yield
   finally:held.pop()
  with tempfile.TemporaryDirectory() as d:
   r=Path(d)/'recipe';r.write_text('{"maximum_unreleased_batches":2}')
   with patch.object(m,'locked',lock),patch.object(m,'capacity_available',side_effect=[(False,2),(True,1)]),patch.object(m,'_publish_locked') as send,patch.object(m.time,'sleep',side_effect=lambda n:self.assertFalse(held)):
    m.publish(dict(root=d,recipe=str(r),database='db'),None,None,None,None,'math','individual',None,Path(d));send.assert_called_once()
 def test_real_publisher_failure_never_retried(self):
  from contextlib import nullcontext
  import p0_qwen_overnight_slot_v67 as m
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'recipe';p.write_text('{"maximum_unreleased_batches":2}')
   with patch.object(m,'locked',return_value=nullcontext()),patch.object(m,'capacity_available',return_value=(True,1)),patch.object(m,'_publish_locked',side_effect=ValueError('unknown partial')) as send:
    with self.assertRaises(ValueError):m.publish(dict(root=d,recipe=str(p),database='db'),None,None,None,None,'math','individual',None,Path(d))
    send.assert_called_once()
