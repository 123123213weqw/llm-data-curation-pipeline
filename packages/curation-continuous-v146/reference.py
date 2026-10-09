"""Fresh independent language controls; no training tokens, no old teacher replay."""
import json
from pathlib import Path
from common import frozen,sha

def reference_scope(domain,lang,registry_sha):
 import hashlib
 return hashlib.sha256(json.dumps(['reference146',domain,lang,registry_sha],separators=(',',':')).encode()).hexdigest()[:24]

def prepare_controls(q,ref,old_ids,make_batch,control_rows):
 ref=Path(ref)
 if ref.exists():raise ValueError('Existing reference attempt: observe only')
 rows,labels,checks=control_rows('code',q['_reference_language'])
 ids=[r['normalized_sha256'] for r in rows]
 if len(ids)!=32 or len(set(ids))!=32 or set(ids)&set(old_ids):raise ValueError('Reference controls are not fresh; preserve existing attempt')
 if len(labels)!=32 or {r['document_id'] for r in labels}!=set(ids):raise ValueError('Independent label coverage mismatch')
 if sum(r['expected']=='keep' for r in labels)!=16 or sum(r['expected']=='drop' for r in labels)!=16:raise ValueError('Original 16/16 reference required')
 meta=dict(kind='reference',domain='code',language=q['_reference_language'],independent=True,strata={r['normalized_sha256']:'code/'+q['_reference_language'] for r in rows})
 make_batch(q,ref,rows,meta)
 frozen(ref/'labels.json',labels);frozen(ref/'verification.json',checks)
 import small_agent.curation.quality_qwen_v35 as quality
 frozen(ref/'REFERENCE_QWEN_V35.json',dict(version=35,domain='code',language=q['_reference_language'],training_eligible=False,natural_corpus_factual_error_rate_certified=False,checker_sha256=sha(quality.__file__),evidence_files=[dict(path=str((ref/n).resolve()),sha256=sha(ref/n)) for n in ['PLAN.json','labels.json','verification.json']]))
 return rows

def finish_reference(q,ref,reference_gate,verify_teacher_scope):
 ref=Path(ref);verify_teacher_scope(q,[ref]);policy=json.loads(Path(q['release_policy']).read_text())['quality']
 gate=reference_gate(ref,json.loads((ref/'labels.json').read_text()),policy)
 frozen(ref/'ACTUAL_GATE_V36.json',gate)
 return gate
