import unittest
from adoption import admissible
class Adoption(unittest.TestCase):
 def data(self):return [dict(name='qwen142_'+str(i),kind='source' if i<2 else 'reference',candidate=None,candidate_train_body_tokens=0,selected=64 if i<2 else 32) for i in range(4)]
 def failure(self):return dict(error='ModuleNotFoundError("No module named \'tree_sitter_language_pack\'")')
 def test_exact_nontraining(self):self.assertTrue(admissible(self.data(),self.failure()))
 def test_unexpected_batch_forbidden(self):
  x=self.data();x[0]['candidate']='unknown'
  with self.assertRaises(ValueError):admissible(x,self.failure())
 def test_other_fault_forbidden(self):
  with self.assertRaises(ValueError):admissible(self.data(),dict(error='unknown'))

class ReceiptRecoveryWhitelist(unittest.TestCase):
 def test_literal_list_allows_exact(self):
  import receipt_adapter,json
  from unittest.mock import patch
  item=dict(name='qwen142_'+'a'*24,folder='gpu_1/x/review',kind='source')
  with patch.object(receipt_adapter.Path,'exists',return_value=True),patch.object(receipt_adapter.Path,'read_text',return_value=json.dumps([item])):
   receipt_adapter.safe_item(item)
 def test_list_does_not_allow_changed_item(self):
  import receipt_adapter,json
  from unittest.mock import patch
  item=dict(name='qwen142_'+'a'*24,folder='gpu_1/x/review',kind='source')
  def read(p,*a,**kw):return json.dumps([item]) if p.name=='RECOVERY_ITEMS.json' else json.dumps({'item':item,'original_item':item})
  with patch.object(receipt_adapter.Path,'exists',return_value=True),patch.object(receipt_adapter.Path,'read_text',read):
   with self.assertRaises(ValueError):receipt_adapter.safe_item(dict(item,folder='gpu_1/changed/review'))
 def test_unsafe_exact_list_path_rejected(self):
  import receipt_adapter,json
  from unittest.mock import patch
  item=dict(name='qwen142_'+'a'*24,folder='../review')
  with patch.object(receipt_adapter.Path,'exists',return_value=True),patch.object(receipt_adapter.Path,'read_text',return_value=json.dumps([item])):
   with self.assertRaises(ValueError):receipt_adapter.safe_item(item)
