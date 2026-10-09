"""Exact sorted-set nonmembership proofs; full exclusion set stays CPU-bound.

Two authenticated adjacent neighbors (or a boundary) prove absence in the full
sorted set, not in a sampled subset. GPU's durable unique reservation enforces
within-run freshness across all lanes; unknown reservations are never cleared.
"""
import hashlib,json,mmap,sqlite3,re,os
from pathlib import Path
from bisect import bisect_left
from common import sha,frozen,fresh
ALGORITHM='sha256-sorted-adjacent-nonmembership-v1'
HEX=re.compile('[a-f0-9]{64}')

def value(x):
 if not isinstance(x,str) or not HEX.fullmatch(x):raise ValueError('Not an exact SHA256 exclusion value')
 return bytes.fromhex(x)
def leaf(kind,i,x):return hashlib.sha256(b'\x00'+kind.encode()+i.to_bytes(8,'big')+value(x)).digest()
def parent(a,b):return hashlib.sha256(b'\x01'+a+b).digest()
def empty(kind):return hashlib.sha256(b'\x02'+kind.encode()+b'empty').hexdigest()

def build_index(H,ids,keys):
 H=Path(H);D=H/'exclusion_index';D.mkdir(exist_ok=False);manifest={};commit=dict(version=144,algorithm=ALGORITHM,original_exclusion_sha256=sha(H/'EXCLUSION_BASE.json'),sets={})
 for kind,values in [('body',ids),('key',keys)]:
  values=sorted(set(values));raw=b''.join(value(x) for x in values);p=D/(kind+'.values.bin');p.write_bytes(raw);manifest[p.name]=sha(p)
  nodes=b''.join(leaf(kind,i,x) for i,x in enumerate(values));level=0
  while nodes:
   p=D/f'{kind}.{level}.bin';p.write_bytes(nodes);manifest[p.name]=sha(p)
   if len(nodes)==32:break
   next_nodes=bytearray()
   for j in range(0,len(nodes),64):
    a=nodes[j:j+32];b=nodes[j+32:j+64] or a;next_nodes.extend(parent(a,b))
   nodes=bytes(next_nodes);level+=1
  commit['sets'][kind]=dict(count=len(values),root=nodes.hex() if nodes else empty(kind),values_sha256=manifest[kind+'.values.bin'],levels=level+1 if nodes else 0)
 frozen(D/'MANIFEST.json',manifest);frozen(H/'EXCLUSION_COMMITMENT.json',commit)
 return commit

class ProofIndex:
 def __init__(self,H):
  self.H=Path(H);D=self.H/'exclusion_index';self.commit=json.loads((self.H/'EXCLUSION_COMMITMENT.json').read_text());self.open=[];self.maps={}
  validate_commit(self.commit)
  manifest=json.loads((D/'MANIFEST.json').read_text())
  for n,h in manifest.items():
   p=D/n
   if p.parent!=D or sha(p)!=h:raise ValueError('Frozen CPU exclusion index changed')
  for kind,s in self.commit['sets'].items():
   self.maps[kind]=[]
   for n in [kind+'.values.bin']+[f'{kind}.{i}.bin' for i in range(s['levels'])]:
    f=(D/n).open('rb');self.open.append(f);self.maps[kind].append(mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ) if f.seek(0,2) else b'')
   if len(self.maps[kind][0])!=s['count']*32 or sha(D/(kind+'.values.bin'))!=s['values_sha256']:raise ValueError('Full sorted vector differs')
 def at(self,kind,i):return self.maps[kind][0][32*i:32*(i+1)].hex()
 def inclusion(self,kind,i):
  s=self.commit['sets'][kind];siblings=[];j=i;n=s['count']
  for nodes in self.maps[kind][1:-1]:
   k=j^1
   if k>=n:k=j
   siblings.append(nodes[32*k:32*(k+1)].hex());j//=2;n=(n+1)//2
  return dict(index=i,value=self.at(kind,i),siblings=siblings)
 def absence(self,kind,x):
  value(x);s=self.commit['sets'][kind];low=0;high=s['count']
  while low<high:
   m=(low+high)//2
   if self.at(kind,m)<x:low=m+1
   else:high=m
  if low<s['count'] and self.at(kind,low)==x:raise ValueError('Excluded prior body/protocol; no replay')
  return dict(left=self.inclusion(kind,low-1) if low else None,right=self.inclusion(kind,low) if low<s['count'] else None)
 def close(self):
  for maps in self.maps.values():
   for m in maps:
    if hasattr(m,'close'):m.close()
  for f in self.open:f.close()

def validate_commit(c):
 if c.get('version')!=144 or c.get('algorithm')!=ALGORITHM or set(c.get('sets',{}))!={'body','key'}:raise ValueError('Unknown full-set commitment')
 for kind,s in c['sets'].items():
  n=s['count'];value(s['root']);value(s['values_sha256'])
  if type(n)is not int or not 0<=n<2**40:raise ValueError('Invalid exclusion count')
  levels=0 if n==0 else (n-1).bit_length()+1
  if s['levels']!=levels or (n==0 and s['root']!=empty(kind)):raise ValueError('Invalid tree shape')

def verify_inclusion(kind,s,p):
 if not isinstance(p,dict) or type(p.get('index'))is not int or not 0<=p['index']<s['count']:raise ValueError('Invalid full-set index')
 i=p['index'];n=s['count'];h=leaf(kind,i,p['value'])
 if len(p['siblings'])!=s['levels']-1:raise ValueError('Incomplete Merkle witness')
 for sibling in p['siblings']:
  sib=value(sibling)
  if i%2:h=parent(sib,h)
  else:
   if i+1>=n and sib!=h:raise ValueError('Odd-node duplication changed')
   h=parent(h,sib)
  i//=2;n=(n+1)//2
 if h.hex()!=s['root']:raise ValueError('Witness differs from full exclusion root')
 return p['index'],p['value']

def verify_absence(kind,s,x,p):
 value(x)
 if not isinstance(p,dict) or set(p)!={'left','right'}:raise ValueError('Invalid absence witness')
 if s['count']==0:
  if p!={'left':None,'right':None}:raise ValueError('Invalid empty-set witness')
  return
 left=verify_inclusion(kind,s,p['left']) if p['left'] is not None else None
 right=verify_inclusion(kind,s,p['right']) if p['right'] is not None else None
 if left is None:
  if right is None or right[0]!=0 or not x<right[1]:raise ValueError('Invalid lower boundary')
 elif right is None:
  if left[0]!=s['count']-1 or not left[1]<x:raise ValueError('Invalid upper boundary')
 elif right[0]!=left[0]+1 or not left[1]<x<right[1]:raise ValueError('Neighbors not adjacent or value not absent')

def make_portable(H,index,ids,keys):
 fresh(ids,keys,[],[])
 return dict(version=144,format=ALGORITHM,commitment_sha256=sha(Path(H)/'EXCLUSION_COMMITMENT.json'),new_body_ids=ids,new_request_keys=keys,body_absence=[index.absence('body',x) for x in ids],key_absence=[index.absence('key',x) for x in keys],old_unknown_ledger_modified=False,full_set_not_sampled=True)

def verify_portable(H,p):
 H=Path(H);c=json.loads((H/'EXCLUSION_COMMITMENT.json').read_text());validate_commit(c)
 if p.get('version')!=144 or p.get('format')!=ALGORITHM or p.get('commitment_sha256')!=sha(H/'EXCLUSION_COMMITMENT.json') or p.get('old_unknown_ledger_modified')is not False or p.get('full_set_not_sampled')is not True:raise ValueError('Portable full-set binding differs')
 fresh(p['new_body_ids'],p['new_request_keys'],[],[])
 if len(p['new_body_ids'])!=len(p['new_request_keys']):raise ValueError('Body/key coverage differs')
 for kind,ids,witness in [('body',p['new_body_ids'],p['body_absence']),('key',p['new_request_keys'],p['key_absence'])]:
  if len(ids)!=len(witness):raise ValueError('Incomplete full-scope absence proof')
  for x,w in zip(ids,witness):verify_absence(kind,c['sets'][kind],x,w)
 return True

def reserve_fresh(H,name,ids,keys):
 if not re.fullmatch('qwen144_[a-f0-9]{24}',name):raise ValueError('Unsafe new global reservation name')
 fresh(ids,keys,[],[])
 if len(ids)!=len(keys):raise ValueError('Incomplete global fresh reservation')
 db=sqlite3.connect(Path(H)/'FRESH_RESERVATIONS.sqlite',timeout=30)
 try:
  db.execute('pragma synchronous=FULL');db.execute('create table if not exists requests(body TEXT PRIMARY KEY,key TEXT UNIQUE NOT NULL,job TEXT NOT NULL) WITHOUT ROWID')
  with db:db.executemany('insert into requests values(?,?,?)',((d,k,name) for d,k in zip(ids,keys)))
 except sqlite3.IntegrityError as e:raise ValueError('Earlier/unknown same-run reservation retained; no replay') from e
 finally:db.close()

def write_input_manifests(H,F):
 H=Path(H);F=Path(F);P=H/'payload'
 files={str(p.relative_to(P)):sha(p) for p in F.rglob('*') if p.is_file()}
 frozen(F/'INPUT_FILES_CPU.json',files)
 gpu={n:h for n,h in files.items() if Path(n).name not in ('candidates.parquet','ALLOCATION_INTENT.json')}
 frozen(F/'INPUT_FILES.json',gpu)

def verify_cpu_input(H,F):
 H=Path(H);F=Path(F);P=H/'payload'
 for n,h in json.loads((F/'INPUT_FILES_CPU.json').read_text()).items():
  p=Path(n)
  if p.is_absolute() or '..' in p.parts or sha(P/p)!=h:raise ValueError('Full CPU input bytes/stock changed')
 gpu=json.loads((F/'INPUT_FILES.json').read_text());full=json.loads((F/'INPUT_FILES_CPU.json').read_text())
 expected={n:h for n,h in full.items() if Path(n).name not in ('candidates.parquet','ALLOCATION_INTENT.json')}
 if gpu!=expected:raise ValueError('GPU/CPU split of evidence differs')
 return True
