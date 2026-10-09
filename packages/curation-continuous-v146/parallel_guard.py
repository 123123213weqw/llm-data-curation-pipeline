"""A distinct source on GPU 0; prior immutable blocked routes cannot compete.
No mutation of prior controller, private ledger, scores or unknown/HOLD state.
"""
import json
from pathlib import Path
from common import sha
COHORT='finewiki_zh_2025_candidate_v1/general_zh/zh'
REASON='Missing independently verified reference; no cross-domain fallback'

def admissible_block(block,gate,cache):
 if block.get('reason')!=REASON or block.get('no_retry') is not True:
  raise ValueError('Only precise missing-reference-file boundary is admissible')
 if gate.get('status')!='passed' or gate.get('holds') or cache.get('status')!='passed' or cache.get('gate')!=gate or cache.get('model_calls')!=0 or cache.get('no_unknown_reissued') is not True:
  raise ValueError('Original exact independent cached reference gate must pass')
 c=gate.get('counts',{})
 if c!={'keep_total':16,'keep_valid':16,'keep_keep':16,'drop_total':16,'drop_valid':16,'drop_keep':0}:
  raise ValueError('Exact complete original 16/16 controls required')
 return True

def verify_guard(H,cfg):
 g=json.loads((Path(H)/'PARALLEL_SCOPE_BOUNDARY.json').read_text())
 for path,h in g['prior_immutable_files'].items():
  if sha(path)!=h:raise ValueError('Prior scope/model concurrency boundary changed')
 cat=json.loads((Path(H)/'SOURCE_CATALOG.json').read_text())
 if len(cat)!=1 or cat[0]['cohort']!=COHORT or cat[0]['logical']!=4:
  raise ValueError('Parallel adjunct must remain exact independent GPU-0 source')
 if g['all_prior_gpu0_routes_blocked'] is not True or g['prior_unknowns_preserved'] is not True or g['stock_body_primary_key'] is not True:
  raise ValueError('Concurrent distinct source proof absent')
 return True

def adopt_reference_copy(source,dest,q,policy,reference_gate,verify_teacher_scope,copytree):
 source=Path(source);dest=Path(dest)
 if dest.exists():raise ValueError('Existing reference copy intent; no repeat')
 before={str(p):sha(p) for p in source.rglob('*') if p.is_file()}
 verify_teacher_scope(q,[source]);gate=reference_gate(source,json.loads((source/'labels.json').read_text()),policy)
 cache=json.loads((source/'REFERENCE_CACHE_ACCEPTANCE.json').read_text())
 admissible_block({'reason':REASON,'no_retry':True},gate,cache)
 copytree(source,dest)
 verify_teacher_scope(q,[dest]);actual=reference_gate(dest,json.loads((dest/'labels.json').read_text()),policy)
 if actual!=gate or before!={str(p):sha(p) for p in source.rglob('*') if p.is_file()}:
  raise ValueError('Readonly original reference/copy changed')
 from common import frozen
 frozen(dest/'ACTUAL_GATE_V36.json',gate)
 return {'gate':gate,'original_files_sha256':before,'teacher_requests_replayed':0,'old_SQL_unchanged':True}

def competing_stock(db,cohorts):
 # Original stock stores source in files and language as records.lang.
 from p0_inventory_supply_v24 import source_query
 q=source_query(db,"r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK')")
 for cohort in cohorts:
  source,domain,lang=cohort.split('/')
  for row in db.execute('SELECT h FROM ('+q+')',(source,domain,lang)):yield row[0]
