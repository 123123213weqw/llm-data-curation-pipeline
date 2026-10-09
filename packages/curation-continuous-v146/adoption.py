"""Narrow exact CPU-only recovery; never replays a settled teacher request."""
def admissible(items,failure):
 if failure.get('error')!='ModuleNotFoundError("No module named \'tree_sitter_language_pack\'")':raise ValueError('Not exact parser dependency fault')
 if len(items)!=4 or {t['kind'] for t in items}!={'reference','source'} or any(t['candidate'] is not None or t['candidate_train_body_tokens']!=0 or t['selected'] not in (32,64) for t in items):raise ValueError('Unexpected production/unknown adoption scope')
 if len({t['name'] for t in items})!=4 or any(not t['name'].startswith('qwen142_') for t in items):raise ValueError('Changed exact four prior jobs')
 return True
