import tempfile,unittest,sys,os
from pathlib import Path
from runtime_cpu import bootstrap
class CPURuntime(unittest.TestCase):
 def test_dependency_precedes_base_for_lazy_reference_gate(self):
  with tempfile.TemporaryDirectory() as td:
   d=Path(td)/'deps';c=Path(td)/'code';d.mkdir();c.mkdir();old=list(sys.path);env=os.environ.get('PYTHONPATH')
   try:bootstrap(dict(runtime_dependencies=str(d),code=str(c)));self.assertEqual(sys.path[:3],[str(d),str(c/'src'),str(c/'scripts')]);self.assertEqual(os.environ['PYTHONPATH'],str(d))
   finally:
    sys.path[:]=old
    if env is None:os.environ.pop('PYTHONPATH',None)
    else:os.environ['PYTHONPATH']=env
 def test_missing_parser_runtime_fails_before_import(self):
  with self.assertRaises(ValueError):bootstrap(dict(runtime_dependencies='/absent-bound-parser',code='/absent-code'))
