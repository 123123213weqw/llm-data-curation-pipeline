import unittest
from token_count import actual_token_count
class Tests(unittest.TestCase):
 def test_flat(self):self.assertEqual(actual_token_count([1,2,3]),3)
 def test_mapping_not_number_of_keys(self):self.assertEqual(actual_token_count({'input_ids':list(range(100)),'attention_mask':[1]*100}),100)
 def test_real_BatchEncoding(self):
  from transformers.tokenization_utils_base import BatchEncoding
  self.assertEqual(actual_token_count(BatchEncoding({'input_ids':list(range(70)),'attention_mask':[1]*70})),70)
 def test_single_batch(self):self.assertEqual(actual_token_count({'input_ids':[[1,2,3]]}),3)
 def test_multiple_batches_fail(self):
  with self.assertRaises(ValueError):actual_token_count([[1,2],[3,4]])
 def test_unknown_shape_fail(self):
  with self.assertRaises(ValueError):actual_token_count('123')
 def test_empty(self):self.assertEqual(actual_token_count([]),0)
