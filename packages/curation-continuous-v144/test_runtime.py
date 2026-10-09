"""Isolated live-entry import tests: no PYTHONPATH inherited from unittest."""
import unittest,tempfile,subprocess,sys,os,json
from pathlib import Path
class RuntimeTests(unittest.TestCase):
 def run_shape(self,missing=False):
  with tempfile.TemporaryDirectory() as d:
   H=Path(d);C=H/'payload/code';(C/'src/small_agent/curation').mkdir(parents=True);(C/'scripts').mkdir()
   for n in ['small_agent/__init__.py','small_agent/curation/__init__.py']:(C/'src'/n).write_text('')
   if not missing:(C/'src/small_agent/curation/store_qwen_v35.py').write_text('class Batch: pass\ndef protocol(): pass\n')
   (C/'scripts/p0_qwen_worker_v35.py').write_text('def job_identity():pass\n')
   source=Path(__file__).parent
   code="import sys;from pathlib import Path;sys.path.insert(0,"+repr(str(source))+");import gpu;r=gpu.original_protocol_runtime(Path("+repr(str(H))+"));assert all(callable(x) for x in r);print('RUNTIME_OK')"
   return subprocess.run([sys.executable,'-I','-B','-c',code],cwd='/',env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'},capture_output=True,text=True,timeout=30)
 def test_isolated_real_entry_loads_original_engine(self):
  z=self.run_shape();self.assertEqual(z.returncode,0,z.stderr);self.assertIn('RUNTIME_OK',z.stdout)
 def test_wrong_engine_path_fails_closed_before_teacher(self):
  z=self.run_shape(True);self.assertNotEqual(z.returncode,0);self.assertIn('ModuleNotFoundError',z.stderr)
 def test_startup_validates_import_before_run_intent(self):
  s=(Path(__file__).parent/'gpu.py').read_text().split('def main():')[1];self.assertLess(s.index('original_protocol_runtime(H)'),s.index("GPU_RUN_INTENT.json"))
 def test_consumer_uses_same_production_import_shape(self):
  s=(Path(__file__).parent/'gpu.py').read_text().split('def consume(')[1].split('def main():')[0];self.assertLess(s.index('original_protocol_runtime(H)'),s.index('reserve_fresh(H'))
