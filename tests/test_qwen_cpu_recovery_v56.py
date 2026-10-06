import unittest
from p0_qwen_cpu_recovery_v56 import failure_guard,terminal_guard
class RecoveryGuardTests(unittest.TestCase):
 def test_confirmed_oom_only(self):failure_guard('failed','oom-kill','oom-kill','A process killed by the OOM killer')
 def test_confirmed_backpressure_only(self):failure_guard('failed','exit-code','exit-code','ValueError: backpressure')
 def test_active_controller_never_replaced(self):
  with self.assertRaises(ValueError):failure_guard('activating','oom-kill','oom-kill','killed by the OOM killer')
 def test_unrelated_failure_never_cleared(self):
  with self.assertRaises(ValueError):failure_guard('failed','exit-code','exit-code','ValueError: unknown')
 def test_oom_needs_real_journal(self):
  with self.assertRaises(ValueError):failure_guard('failed','oom-kill','oom-kill','')
 def test_complete_known_terminal(self):terminal_guard(dict(selected=64,considered=64,stop_reason=None))
 def test_incomplete_terminal_never_rescored(self):
  with self.assertRaises(ValueError):terminal_guard(dict(selected=64,considered=63,stop_reason=None))
 def test_unknown_terminal_preserved(self):
  with self.assertRaises(ValueError):terminal_guard(dict(selected=64,considered=64,stop_reason='timeout'))
 def test_empty_terminal_preserved(self):
  with self.assertRaises(ValueError):terminal_guard({})
if __name__=='__main__':unittest.main()
