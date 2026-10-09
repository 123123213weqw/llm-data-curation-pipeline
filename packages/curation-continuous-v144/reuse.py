"""Reuse exact live backends and their owned transparent aliases; never mutate them."""
import json,time
from pathlib import Path
from urllib.request import urlopen
from common import sha,show,validate_binding,terminal_ok

def verify_reuse(H,cfg):
 from gpu import owned_idle
 owner=cfg['prior_alias_owner'];s=show(owner['unit'])
 if any(s.get(k)!=owner[k] for k in ('MainPID','InvocationID','ControlGroup')) or s['ActiveState'] not in ('active','activating'):raise ValueError('Bound alias owner changed; no restart')
 prior=Path(cfg['prior_remote_root'])
 for p,h in cfg['prior_complete_files'].items():
  if sha(p)!=h:raise ValueError('Prior settled receipt changed: '+p)
 bindings={}
 for k,r in cfg['backends'].items():
  b=cfg['reuse_bindings'][k]
  if not validate_binding(show(r['unit']),b):raise ValueError('Prior backend identity changed')
  owned_idle(H,cfg,r,b)
  for port in [r['port']]+[p for g,p in cfg['aliases'].items() if cfg['logical_lane'][g]==int(k)]:
   with urlopen(f'http://127.0.0.1:{port}/v1/models',timeout=8) as x:models=json.load(x)['data']
   if not any((m['id'],m['root'],m['max_model_len'])==('qwen3.8-27b-fp8',cfg['model'],32768) for m in models):raise ValueError('Exact inherited endpoint differs')
  bindings[int(k)]=b
 return bindings
