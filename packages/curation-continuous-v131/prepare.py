"""Continuous original source/individual selection, preheated disk queue bounded four."""
import json,os,shutil,sqlite3,sys,time
from pathlib import Path
from collections import Counter
from common import sha,frozen,atomic,fresh,rolling,train_route_ok,cpu_pressure
from flow import verify_bound,can_prepare,block,blocked,choose_mode,safe_scope

def main():
 H=Path(sys.argv[1]);cfg=json.loads((H/'CONFIG.json').read_text());verify_bound(H,cfg);P=H/'payload';C=Path(cfg['code']);sys.path[:0]=[str(C/'src'),str(C/'scripts')]
 from p0_qwen_overnight_slot_v67 import locked
 from selection import select_fresh,bind_exclusions,fresh_clause,route_complete
 from p0_inventory_supply_v11 import retrieve
 from p0_inventory_supply_v24 import sample,source_query
 from p0_arrow_reader_v15 import ArrowRawReader
 from small_agent.curation.quality_qwen_v35 import source_gate,reference_gate,verify_teacher_scope,make_batch
 from small_agent.curation.release_gates_v5 import EvalScreen
 from small_agent.curation.supply_control import digest
 from small_agent.curation.full_inventory_v11 import layer
 from small_agent.curation.store_qwen_v35 import Batch,protocol
 from p0_qwen_worker_v35 import job_identity
 import pyarrow as pa,pyarrow.parquet as pq
 frozen(H/'PREPARE_RUN_INTENT.json',dict(unix=time.time(),pid=os.getpid(),continuous=True,no_teacher_requests=True))
 ex=json.loads((H/'EXCLUSION_BASE.json').read_text());old_ids=set(ex['body_ids']);old_keys=set(ex['request_keys']);allocated=set(old_ids);new_ids=set();new_keys=set();ordinal=0;turns=Counter();exhausted=set();calibrating={};catalog=json.loads((H/'SOURCE_CATALOG.json').read_text());prepared=[]
 try:
  while True:
   if (H/'STOP_NEW.json').exists():break
   progress=False
   for sc in catalog:
    atomic(H/'CURRENT_SOURCE.json',dict(unix=time.time(),cohort=sc['cohort'],scope=sc['scope']))
    scope=safe_scope(sc['scope']);gpu=sc['logical'];cohort=sc['cohort'];source,domain,lang=cohort.split('/')
    if scope in exhausted or blocked(H,scope):continue
    q=json.loads(Path(sc['config']).read_text());q=dict(q,batch_train_body_tokens=cfg['candidate_train_target']//4);root=Path(q['root']);src=Path(sc['source']);ref=Path(sc['reference']);policy=json.loads(Path(q['release_policy']).read_text());perf=json.loads(Path(cfg['performance']).read_text())
    while not can_prepare(H,cfg['maximum_backlog']) or cpu_pressure()['reasons']:
     atomic(H/'PREPARE_STATUS.json',dict(unix=time.time(),stage='WAIT_BOUNDED_QUEUE_OR_CPU_PRESSURE',cohort=cohort,prepared=len(prepared),backlog=__import__('flow').backlog(H)))
     if (H/'STOP_NEW.json').exists():break
     time.sleep(5)
    if (H/'STOP_NEW.json').exists():break
    for path,h in sc['immutable_files'].items():
     if sha(path)!=h:raise ValueError('Source/reference/config changed: '+path)
    if q['allow_api'] is not False or q['auto_training'] is not False:raise ValueError('No paid/training required')
    rg=reference_gate(ref,json.loads((ref/'labels.json').read_text()),policy['quality'])
    if rg['status']!='passed':block(H,scope,'Independent reference expired/hold');continue
    db=sqlite3.connect(root/'stock.sqlite',timeout=60);db.row_factory=sqlite3.Row
    try:
     registry=json.loads((root/'REGISTRY.json').read_text());reader=ArrowRawReader();bind_exclusions(db,allocated)
     if not (src/'ACTUAL_GATE_V36.json').exists():
      if scope in calibrating:
       if (H/'events'/(calibrating[scope]+'_SOURCE_TERMINAL.json')).exists():
        if not (src/'ACTUAL_GATE_V36.json').exists():block(H,scope,'Source calibration terminal without gate')
       continue
      # Full source-specific 64/stratum fresh corpus QA; never borrow another source's scores.
      selected,pop=sample(db,source,domain,lang,64,gate_clause=fresh_clause("r.gate IN ('CANDIDATE','CANDIDATE_FALLBACK') AND r.job IS NULL"))
      groups={}
      for r in selected:
       groups.setdefault(r['stratum'],[]).append(r)
      records=[r for s in sorted(groups) for r in groups[s][:64]]
      if not records or set(groups)!=set(pop) or any(len(v)!=64 for v in groups.values()):block(H,scope,'No complete fresh source64 stratum sample');continue
      rows=retrieve(q,db,records,registry,reader);kind='source';mode='source';name='qwen131_'+digest([cohort,kind,[r['h'] for r in records],sha(q['qwen_registry'])])[:24];F=P/f'gpu_{gpu}'/name;F.mkdir(parents=True,exist_ok=False)
      make_batch(q,F/'review',rows,dict(kind='source',source_id=source,domain=domain,language=lang,population=pop,strata={r['h']:r['stratum'] for r in records},registry_sha256=sha(root/'REGISTRY.json')))
      # This is the new calibration's sole portable Batch; create scope symlink, not a second attempt.
      src.parent.mkdir(parents=True,exist_ok=True);src.symlink_to(F/'review',target_is_directory=True)
      candidate=None;calibrating[scope]=name
     else:
      verify_teacher_scope(q,[src,ref]);sg=source_gate(src,policy['quality'])
      if sg!=json.loads((src/'ACTUAL_GATE_V36.json').read_text()):raise ValueError('Actual source gate differs')
      mode=choose_mode(turns[scope],sg);records=[]
      with locked(root/'queue.lock'):
       records=select_fresh(db,q,source,domain,lang,sg,mode,perf)
       if not records:
        # Try the other original route; no-route is not "all corpus washed".
        mode='individual' if mode=='source_audit' else 'source_audit';records=select_fresh(db,q,source,domain,lang,sg,mode,perf)
       if not records:
        exhausted.add(scope);frozen(H/'scope_terminals'/scope,dict(unix=time.time(),cohort=cohort,state='NO_COMPLETE_UNALLOCATED_SPLIT_ROUTE',not_all_stock_washed=True));continue
       if not route_complete(records,sg,mode):
        exhausted.add(scope);frozen(H/'scope_terminals'/scope,dict(unix=time.time(),cohort=cohort,state='FRESH_ROUTE_INCOMPLETE_LOCAL_ONLY',mode=mode,selected=len(records),splits=dict(Counter(r['split'] for r in records)),strata=sorted(set(r['stratum'] for r in records)),excluded_body_count=len(allocated),quality_gates_unchanged=True,not_all_stock_washed=True));continue
       name='qwen131_'+digest([cohort,mode,sha(q['qwen_registry']),[r['h'] for r in records]])[:24];F=P/f'gpu_{gpu}'/name;F.mkdir(parents=True,exist_ok=False)
       frozen(F/'ALLOCATION_INTENT.json',dict(unix=time.time(),job=name,body_ids=[r['h'] for r in records],original_split=True,mode=mode,approved_strata=sg['approved_strata']))
       with db:
        db.execute('insert into jobs(name,source,mode,state) values(?,?,?,?)',(name,source,mode,'PREPARING_V131'))
        for r in records:
         if db.execute("update records set job=? where h=? AND job IS NULL AND gate IN ('CANDIDATE','CANDIDATE_FALLBACK')",(name,r['h'])).rowcount!=1:raise ValueError('Stock race; preserve assigned scope')
      t0=time.monotonic();rows=retrieve(q,db,records,registry,reader);rows,_=EvalScreen(Path(q['eval_registry']),policy['evaluation']).filter(rows)
      known=sqlite3.connect('file:'+str(q['database'])+'?mode=ro',uri=True)
      try:rows=[r for r in rows if not known.execute('select 1 from documents where body_sha=?',(r['normalized_sha256'],)).fetchone()]
      finally:known.close()
      if not rows or {r['split'] for r in rows}!={'train','validation','test'}:
       with locked(root/'queue.lock'):
        with db:db.execute("update jobs set state='HOLD_ISOLATION' where name=?",(name,));db.execute("update records set gate='HOLD_ISOLATION' where job=?",(name,))
       block(H,scope,'Isolation removed independent split; preserve scope');continue
      candidate=F/'candidates.parquet';pq.write_table(pa.Table.from_pylist(rows),candidate,compression='zstd')
      frozen(F/'CANDIDATE_BINDING.json',dict(teacher='qwen',teacher_registry_sha256=sha(q['qwen_registry']),candidate_sha256=sha(candidate),registry_sha256=sha(root/'REGISTRY.json'),source_id=source,domain=domain,language=lang,allocation_sha256=digest(sorted(r['h'] for r in records)),controller_sha256=sha(__file__)))
      review,population=(rows,{s:sum(layer(r)==s for r in rows) for s in {layer(r) for r in rows}}) if mode=='individual' else rolling(rows,4,digest,layer)
      make_batch(q,F/'review',review,dict(kind='batch',mode=mode,candidate_sha256=sha(candidate),strata={r['normalized_sha256']:layer(r) for r in review},population=population,source_manifest_sha256=sha(src/'PLAN.json')));kind='batch';turns[scope]+=1
     b=Batch(F/'review/batch')
     try:ids=list(b.docs);keys=[job_identity(protocol(d,b.prompt,b.schema,b.registry['judges']['qwen'])) for d in b.docs.values()]
     finally:b.close()
     fresh(ids,keys,old_ids|new_ids,old_keys|new_keys);new_ids.update(ids);new_keys.update(keys);allocated.update(r['h'] for r in records)
     releasecfg=dict(q,_source=source);frozen(F/'RELEASE_CONFIG.json',releasecfg)
     item=dict(gpu=gpu,name=name,kind=kind,scope=scope,cohort=cohort,mode=mode,ordinal=ordinal,folder=str((F/'review').relative_to(P)),source=str(src),reference=str(ref),config=str(F/'RELEASE_CONFIG.json'),candidate=str(candidate) if candidate else None,selected=len(ids),candidate_documents=len(rows),candidate_train_body_tokens=sum(r['own_text_tokens'] for r in rows if r['split']=='train') if candidate else 0)
     frozen(F/'PREHEATED.json',item);frozen(F/'EXCLUSION_PROOF.json',dict(old_attempted_body_ids=sorted(old_ids|new_ids-set(ids)),old_request_keys=sorted(old_keys|new_keys-set(keys)),new_body_ids=ids,new_request_keys=keys,disjoint=True,preserved_unknown_keys=ex['unknown_keys'],old_unknown_ledger_modified=False))
     frozen(F/'INPUT_FILES.json',{str(p.relative_to(P)):sha(p) for p in F.rglob('*') if p.is_file() and p.name!='candidates.parquet'})
     if kind=='batch':
      with locked(root/'queue.lock'):
       with db:db.execute("update jobs set state='CPU_PREHEATED_V131_NOT_READY' where name=?",(name,))
     frozen(H/'queue'/f'{ordinal:09d}_{gpu}_{name}.json',item);prepared.append(name);ordinal+=1;progress=True
     atomic(H/'PREPARE_STATUS.json',dict(unix=time.time(),stage='CONTINUOUS_PREHEAT_READY_FOR_TRANSPORT',prepared=len(prepared),last_task=item,continuous=True))
    finally:db.close()
   if all(sc['scope'] in exhausted or blocked(H,sc['scope']) for sc in catalog):break
   if not progress:time.sleep(5)
  frozen(H/'PRODUCER_DONE.json',dict(unix=time.time(),jobs=prepared,exhausted_scopes=sorted(exhausted),blocked_scopes=[s['cohort'] for s in catalog if blocked(H,s['scope'])],not_all_stock_washed=True))
 except BaseException as e:
  frozen(H/'PREPARE_FAILURE.json',dict(unix=time.time(),error=repr(e),no_auto_retry=True));raise
if __name__=='__main__':main()
