"""Producer seal is a queue binding, not permission to forget late arrivals."""
import json
from pathlib import Path
from flow import event_terminal

def sealed_names(H):
 H=Path(H)
 if not (H/'PRODUCER_DONE.json').exists():return None
 tasks=[json.loads(p.read_text()) for p in (H/'queue').glob('*.json')]
 names=[t['name'] for t in tasks]
 if len(names)!=len(set(names)):raise ValueError('Repeated immutable queue item')
 declared=json.loads((H/'PRODUCER_DONE.json').read_text())['jobs']
 if len(declared)!=len(set(declared)) or set(declared)!={t['name'] for t in tasks if not t.get('recovery')}:raise ValueError('Producer seal differs from full durable queue')
 return set(names)

def producer_notifiable(H,sent):
 names=sealed_names(H)
 return names is not None and names<=set(sent)

def fully_drained(H,sent,imported,unfinished):
 names=sealed_names(H)
 return names is not None and names<=set(sent) and names<=set(imported) and unfinished==0 and all(event_terminal(H,n) for n in names)
