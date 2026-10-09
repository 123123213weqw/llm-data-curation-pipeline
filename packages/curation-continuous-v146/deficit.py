"""Supply-domain deficit ordering. Not a training sampler or token-credit ledger."""
import json,sqlite3
from pathlib import Path
from fractions import Fraction
from common import sha
from flow import event_terminal

def validate_targets(targets):
 if set(targets)!={'general_en','general_zh','code','technical','math'} or any(type(n) is not int or n<=0 for n in targets.values()):
  raise ValueError('Complete original positive supply targets required')
 return targets

def next_source(catalog,account,turns):
 targets=validate_targets(account['targets']);ready=account['verified_ready'];pending=account['pending_candidate_reservations']
 for d in targets:
  if any(type(x.get(d,0)) is not int or x.get(d,0)<0 for x in (ready,pending)):raise ValueError('Invalid domain accounting')
 if not catalog:return None
 for sc in catalog:
  if sc['cohort'].split('/')[1] not in targets:raise ValueError('Unknown domain: no generic fallback')
 # Ratio-fill prevents large English stock from hiding a small technical deficit.
 # In-flight reservations affect ordering only, never READY counts. Equal fill rotates scopes.
 return min(catalog,key=lambda sc:(Fraction(ready.get(sc['cohort'].split('/')[1],0)+pending.get(sc['cohort'].split('/')[1],0),targets[sc['cohort'].split('/')[1]]),turns.get(sc['scope'],0),sc['cohort']))

def observe_accounting(H,cfg):
 H=Path(H);recipe=Path(cfg['supply_recipe'])
 if sha(recipe)!=cfg['supply_recipe_sha256']:raise ValueError('Frozen supply targets changed')
 targets=validate_targets(json.loads(recipe.read_text())['targets_by_domain'])
 db=sqlite3.connect('file:'+str(cfg['database'])+'?mode=ro',uri=True,timeout=30)
 try:
  db.execute('BEGIN')
  # releases are original certified corpus supply, not paid requests or heldout.
  ready={d:int(n) for d,n in db.execute('SELECT b.domain,SUM(r.train_tokens) FROM releases r JOIN batches b ON b.batch_id=r.batch_id GROUP BY b.domain')}
 finally:db.close()
 pending={d:0 for d in targets};active=[]
 for p in sorted((H/'queue').glob('*.json')):
  t=json.loads(p.read_text())
  if event_terminal(H,t['name']):continue
  d=t['cohort'].split('/')[1]
  if d not in pending:raise ValueError('Unknown queued domain')
  n=t.get('candidate_train_body_tokens',0)
  if type(n) is not int or n<0:raise ValueError('Invalid pending reservation')
  pending[d]+=n;active.append(t['scope'])
 return dict(targets=targets,verified_ready=ready,pending_candidate_reservations=pending,active_scopes=sorted(set(active)),pending_not_READY=True,legacy_scalar_not_counted=True,not_training_sampling=True)
