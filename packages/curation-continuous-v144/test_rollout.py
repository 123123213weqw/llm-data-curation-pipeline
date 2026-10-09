import tempfile,unittest,json
from pathlib import Path
from rollout import exact_units,cpu_drained
class Rollout(unittest.TestCase):
 def test_active_exact_identity(self):
  b={'u':dict(MainPID='1',InvocationID='x',ControlGroup='/x',ActiveState='activating')};self.assertTrue(exact_units(b,b))
 def test_changed_pid_failclosed(self):
  b={'u':dict(MainPID='1',InvocationID='x',ControlGroup='/x')}
  with self.assertRaises(ValueError):exact_units({'u':dict(b['u'],MainPID='2')},b)
 def test_changed_inv_failclosed(self):
  b={'u':dict(MainPID='1',InvocationID='x',ControlGroup='/x')}
  with self.assertRaises(ValueError):exact_units({'u':dict(b['u'],InvocationID='y')},b)
 def test_allowed_terminal_not_restart(self):
  b={'u':dict(MainPID='1',InvocationID='x',ControlGroup='/x')};self.assertTrue(exact_units({'u':dict(MainPID='0',ActiveState='inactive')},b,True))
 def test_unsealed_not_drained(self):
  with tempfile.TemporaryDirectory() as td:self.assertFalse(cpu_drained(Path(td),{}))
 def test_started_publication_not_interrupted(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'PRODUCER_DONE.json').write_text('{}');(h/'PIPELINE_FINAL.json').write_text('{}');self.assertFalse(cpu_drained(h,{'u':dict(MainPID='100')}))
 def test_all_terminal_required(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'queue').mkdir();(h/'events').mkdir();(h/'queue/1.json').write_text('{"name":"x"}');(h/'PRODUCER_DONE.json').write_text('{"jobs":["x"]}');(h/'PIPELINE_FINAL.json').write_text('{"errors":[]}')
   with self.assertRaisesRegex(ValueError,'not terminal'):cpu_drained(h,{})
 def test_preserve_failure(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'queue').mkdir();(h/'events').mkdir();(h/'PRODUCER_DONE.json').write_text('{"jobs":[]}');(h/'PIPELINE_FINAL.json').write_text('{"errors":["unknown"]}')
   with self.assertRaisesRegex(ValueError,'genuine failure'):cpu_drained(h,{})
 def test_fully_drained(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'queue').mkdir();(h/'events').mkdir();(h/'PRODUCER_DONE.json').write_text('{"jobs":[]}');(h/'PIPELINE_FINAL.json').write_text('{"errors":[]}');self.assertTrue(cpu_drained(h,{}))
