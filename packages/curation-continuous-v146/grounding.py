"""Narrow pre-request grounding HOLD. Preserve the whole batch; never resample it."""
import hashlib,time
from common import frozen,sha

class GroundingHold(Exception):
 def __init__(self,documents):
  self.documents=documents
  super().__init__('Original unique evidence absent; whole prepared scope held without API')

def protocol_plan(batch,protocol,identity,spans_fn=None):
 if spans_fn is None:
  from small_agent.curation.evidence_ids_qwen_v35 import spans
  spans_fn=spans
 ids=[];keys=[];bad=[]
 for d in batch.docs.values():
  if hashlib.sha256(d['document_text'].encode()).hexdigest()!=d['body_sha256']:
   raise ValueError('Actual document body differs; not a known grounding hold')
  try:spans_fn(d)
  except ValueError as e:
   if type(e) is not ValueError or str(e)!='No uniquely grounded evidence; hold without API':raise
   bad.append(dict(document_id=d['document_id'],body_sha256=d['body_sha256'],reason=str(e)))
   continue
  ids.append(d['document_id']);keys.append(identity(protocol(d,batch.prompt,batch.schema,batch.registry['judges']['qwen'])))
 if bad:raise GroundingHold(bad)
 return ids,keys

def record_grounding_hold(H,F,root,db,name,kind,scope,cohort,records,hold,locked):
 # No job is submitted, no surviving reviews substituted, no partial QA counted.
 if (F/'PREHEATED.json').exists() or (F/'review/batch/worker').exists():
  raise ValueError('Possible existing attempt; cannot mark a pre-request HOLD')
 files={str(p):sha(p) for p in F.rglob('*') if p.is_file()}
 frozen(F/'GROUNDING_HOLD_NOT_SENT.json',dict(unix=time.time(),job=name,kind=kind,
  scope=scope,cohort=cohort,bad_documents=hold.documents,body_ids=[r['h'] for r in records],
  original_files_sha256=files,full_prepared_batch_preserved=True,teacher_requests=0,
  no_retry=True,quality_gates_changed=False,not_READY=True))
 if kind=='batch':
  with locked(root/'queue.lock'):
   with db:
    if db.execute("update jobs set state='HOLD_GROUNDING_NOT_SENT' where name=? AND state='PREPARING_V146'",(name,)).rowcount!=1:
     raise ValueError('Allocated job changed; preserve and fail closed')
    actual=db.execute('select count(*) from records where job=?',(name,)).fetchone()[0]
    if actual!=len(records):raise ValueError('Allocated full body scope changed')
    db.execute("update records set gate='HOLD_GROUNDING_NOT_SENT' where job=?",(name,))
 frozen(H/'events'/(name+'_PREPARE_HOLD.json'),dict(unix=time.time(),scope=scope,
  cohort=cohort,state='HOLD_GROUNDING_NOT_SENT',evidence_sha256=sha(F/'GROUNDING_HOLD_NOT_SENT.json'),
  no_teacher_requests=True,no_retry=True,other_cohorts_may_continue=True))
