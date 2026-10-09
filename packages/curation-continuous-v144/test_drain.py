import tempfile,unittest
from pathlib import Path
from common import frozen
from drain import producer_notifiable,fully_drained
class DrainTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.H=Path(self.tmp.name);(self.H/'queue').mkdir();(self.H/'events').mkdir()
 def tearDown(self):self.tmp.cleanup()
 def q(self,name,recovery=False):frozen(self.H/'queue'/(name+'.json'),dict(name=name,recovery=recovery))
 def done(self,names):frozen(self.H/'PRODUCER_DONE.json',dict(jobs=names))
 def terminal(self,n):frozen(self.H/'events'/(n+'_PUBLICATION_TERMINAL.json'),dict(state='READY_INTERNAL'))
 def test_unsealed_producer_never_finishes(self):self.q('a');self.terminal('a');self.assertFalse(fully_drained(self.H,{'a'},{'a'},0))
 def test_late_queued_batch_before_seal_not_forgotten(self):
  self.q('a');self.terminal('a');sent={'a'};imported={'a'};self.q('b');self.done(['a','b']);self.assertFalse(producer_notifiable(self.H,sent));self.assertFalse(fully_drained(self.H,sent,imported,0));self.terminal('b');self.assertTrue(fully_drained(self.H,{'a','b'},{'a','b'},0))
 def test_imported_not_published_cannot_finish(self):self.q('a');self.done(['a']);self.assertFalse(fully_drained(self.H,{'a'},{'a'},0))
 def test_writer_unfinished_cannot_finish(self):self.q('a');self.done(['a']);self.terminal('a');self.assertFalse(fully_drained(self.H,{'a'},{'a'},1))
 def test_all_explicit_HOLD_is_terminal_not_READY(self):self.q('a');self.done(['a']);frozen(self.H/'events/a_TRANSPORT_HOLD.json',dict(not_READY=True));self.assertTrue(fully_drained(self.H,{'a'},{'a'},0))
 def test_missing_sealed_queue_item_failclosed(self):
  self.q('a');self.done(['a','b'])
  with self.assertRaises(ValueError):producer_notifiable(self.H,{'a','b'})
 def test_extra_queue_not_in_seal_failclosed(self):
  self.q('a');self.q('b');self.done(['a'])
  with self.assertRaises(ValueError):producer_notifiable(self.H,{'a','b'})
 def test_prior_CPU_recovery_separate_from_new_producer_jobs(self):self.q('old',True);self.q('a');self.done(['a']);self.assertFalse(producer_notifiable(self.H,{'a'}));self.assertTrue(producer_notifiable(self.H,{'a','old'}))
if __name__=='__main__':unittest.main()
