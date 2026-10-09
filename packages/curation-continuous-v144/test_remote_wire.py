import unittest,subprocess,sys,shlex
from remote_wire import script_transport
class Wire(unittest.TestCase):
 def test_small_script_does_not_use_raw_stdin(self):
  cmd,inp,mode=script_transport('print("x")');self.assertIsNone(inp);self.assertEqual(mode,'compressed-argument');self.assertLess(len(cmd),1000)
 def test_large_frozen_script_is_packed(self):
  import random
  r=random.Random(0);code='#'+''.join(r.choice('abcdef0123456789') for _ in range(10000))+'\nprint("x")';cmd,inp,mode=script_transport(code,128);self.assertEqual(mode,'compressed-stdin');self.assertIsNotNone(inp);self.assertLess(len(cmd),1000)
 def test_exact_small_roundtrip(self):
  cmd,inp,mode=script_transport('print("中文 exact")');wrapper=shlex.split(cmd)[-1];z=subprocess.run([sys.executable,'-B','-c',wrapper],input=inp,capture_output=True,text=True,timeout=10);self.assertEqual(z.stdout,'中文 exact\n');self.assertEqual(z.returncode,0)
 def test_exact_large_roundtrip(self):
  import random
  r=random.Random(1);code='#'+''.join(r.choice('abcdef0123456789') for _ in range(10000))+'\nprint("exact")';cmd,inp,mode=script_transport(code,128);z=subprocess.run([sys.executable,'-B','-c',shlex.split(cmd)[-1]],input=inp,capture_output=True,text=True,timeout=10);self.assertEqual(z.stdout,'exact\n');self.assertEqual(z.returncode,0)
 def test_invalid_input(self):
  with self.assertRaises(ValueError):script_transport('')
 def test_shell_data_not_executed(self):
  cmd,inp,mode=script_transport('print("$HOME;\"quoted\"")');self.assertNotIn('$HOME',cmd)
