import tempfile,unittest,json
from pathlib import Path
from reference import prepare_controls,reference_scope,finish_reference
from flow import event_terminal,first_ready
class Reference(unittest.TestCase):
 def test_scope_independent_of_corpus(self):self.assertEqual(reference_scope('code','rust','a'),reference_scope('code','rust','a'))
 def test_scope_different_language(self):self.assertNotEqual(reference_scope('code','rust','a'),reference_scope('code','python','a'))
 def test_scope_different_teacher(self):self.assertNotEqual(reference_scope('code','rust','a'),reference_scope('code','rust','b'))
 def test_existing_attempt_never_reprepared(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaisesRegex(ValueError,'Existing reference'):prepare_controls({'_reference_language':'rust'},td,set(),None,None)
 def test_known_body_not_replayed(self):
  with tempfile.TemporaryDirectory() as td:
   rows=[{'normalized_sha256':str(i)} for i in range(32)]
   with self.assertRaisesRegex(ValueError,'not fresh'):prepare_controls({'_reference_language':'rust'},Path(td)/'ref',{'2'},None,lambda *a:(rows,[],[]))
 def test_only_complete_controls(self):
  with tempfile.TemporaryDirectory() as td:
   with self.assertRaisesRegex(ValueError,'not fresh'):prepare_controls({'_reference_language':'rust'},Path(td)/'ref',set(),None,lambda *a:([],[],[]))
 def test_reference_terminal_releases_queue_not_tokens(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'events').mkdir();(h/'events/ref_REFERENCE_TERMINAL.json').write_text(json.dumps({'state':'REFERENCE_CALIBRATED','not_READY':True}));self.assertTrue(event_terminal(h,'ref'));self.assertTrue(first_ready({'name':'ref'},{'name':'ref','state':'REFERENCE_CALIBRATED'}));self.assertFalse(first_ready({'name':'ref'},{'name':'ref','state':'HOLD_REFERENCE'}))
 def test_reference_finish_hold_preserved(self):
  with tempfile.TemporaryDirectory() as td:
   h=Path(td);(h/'labels.json').write_text('[]');(h/'policy.json').write_text('{"quality":{}}');q={'release_policy':str(h/'policy.json')};g=finish_reference(q,h,lambda *a:{'status':'hold'},lambda *a:None);self.assertEqual(g['status'],'hold');self.assertTrue((h/'ACTUAL_GATE_V36.json').exists())
