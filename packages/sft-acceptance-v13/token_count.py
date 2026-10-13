"""Exact chat token count across list/BatchEncoding/tensor shapes; no compile or model request."""
def actual_token_count(encoded):
 if hasattr(encoded,'input_ids'):encoded=encoded.input_ids
 elif isinstance(encoded,dict):encoded=encoded['input_ids']
 if hasattr(encoded,'tolist'):encoded=encoded.tolist()
 if isinstance(encoded,list) and len(encoded)==1 and isinstance(encoded[0],list):encoded=encoded[0]
 if not isinstance(encoded,list) or not all(type(x) is int for x in encoded):raise ValueError('unknown or multi-batch token shape')
 return len(encoded)
