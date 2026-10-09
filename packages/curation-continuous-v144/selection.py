"""Original v67 routing with exclusions applied before reserve/rank/LIMIT.

Only known, complete-route absence is a source-local terminal. Invalid metadata,
SQL errors, changed scope and stock races are never caught as a shortage.
"""
from common import train_route_ok

def bind_exclusions(db,ids):
 db.execute('CREATE TEMP TABLE excluded_body(h TEXT PRIMARY KEY) WITHOUT ROWID')
 db.executemany('INSERT INTO excluded_body(h) VALUES(?)',((h,) for h in sorted(set(ids))))

def fresh_clause(clause):
 return '('+clause+') AND NOT EXISTS (SELECT 1 FROM temp.excluded_body e WHERE e.h=r.h)'

def select_fresh(db,cfg,source,domain,lang,sg,mode,perf):
 from p0_inventory_supply_v24 import source_query
 from p0_heldout_reserve_v24 import select_reserve
 approved=sg['approved_strata'];params=[source,domain,lang]
 clause="r.gate='CANDIDATE' AND r.job IS NULL"
 if mode=='source_audit':
  if not approved:return []
  clause+=' AND r.stratum IN ('+','.join('?' for _ in approved)+')';params+=approved
 elif mode=='individual':
  clause="r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL"
  if approved:clause+=" AND (r.gate='CANDIDATE_FALLBACK' OR r.stratum NOT IN ("+','.join('?' for _ in approved)+'))';params+=approved
 else:raise ValueError('Unknown original selection mode')
 q=source_query(db,fresh_clause(clause))
 strata=approved if mode=='source_audit' else [r[0] for r in db.execute('SELECT DISTINCT stratum FROM ('+q+") WHERE split='train'",params)]
 hq,hparams=(q,params) if mode=='source_audit' else (source_query(db,fresh_clause("r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL")),[source,domain,lang])
 held=select_reserve(db,hq,hparams,strata,target_tokens=perf.get('heldout_target_tokens_per_stratum',16384),maximum_documents_per_stratum=128 if mode=='source_audit' else 32)
 if held is None:return []
 limit=cfg['maximum_batch_documents']*perf['fast_batch_size_multiplier'] if mode=='source_audit' else 512-len(held)
 target=cfg['batch_train_body_tokens']*perf['fast_batch_size_multiplier'] if mode=='source_audit' else cfg['batch_train_body_tokens']
 if limit<1:return []
 chosen=[];n=0
 for r in db.execute(q+" AND r.split='train' ORDER BY r.rank LIMIT ?",[*params,limit]):
  chosen.append(r);n+=r['n']
  if n>=target:break
 return chosen+held if chosen else []

def route_complete(records,sg,mode):
 # Do not catch ValueError from train_route_ok: only recognize exact absence here.
 if not records or {r['split'] for r in records}!={'train','validation','test'}:return False
 if mode=='source_audit':
  train_route_ok(records,sg['approved_strata'])
 elif mode!='individual':raise ValueError('Unknown mode')
 return True
