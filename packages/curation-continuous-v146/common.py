import hashlib,json,os,subprocess
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def sync_dir(p):
 fd=os.open(str(p),os.O_RDONLY|os.O_DIRECTORY)
 try:os.fsync(fd)
 finally:os.close(fd)
def frozen(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 sync_dir(p.parent)
def atomic(p,v):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp')
 with t.open('w') as f:json.dump(v,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 os.replace(t,p);sync_dir(p.parent)
def show(u):
 r=subprocess.run(['systemctl','--user','show',u,'-p','LoadState','-p','MainPID','-p','ActiveState','-p','ControlGroup','-p','InvocationID','-p','Result','-p','ExecMainStatus'],check=True,capture_output=True,text=True,timeout=10)
 return dict(x.split('=',1) for x in r.stdout.splitlines())
def identity(pid):
 p=Path('/proc',str(pid))
 return p.stat().st_uid,p.joinpath('cgroup').read_text().strip().splitlines()[0].split(':')[-1],p.joinpath('stat').read_text().rsplit(') ',1)[1].split()[19]
def model_binding(s):
 return dict(s,startticks=identity(s['MainPID'])[2])
def validate_binding(s,b):
 if s['MainPID']=='0':return False
 for k in ['MainPID','ControlGroup','InvocationID']:
  if s.get(k)!=b.get(k) or not s.get(k):raise ValueError('Owned model binding changed: '+k)
 uid,cg,ticks=identity(s['MainPID'])
 if uid!=os.getuid() or cg!=b['ControlGroup'] or ticks!=b['startticks']:raise ValueError('Owned model process changed')
 return True
def terminal_ok(v):
 if v.get('stop_reason') or v['considered']!=v['selected']:raise ValueError('Incomplete or unknown request; never retry')
 if not v['local_only'] or v['paid_api_requests']!=0 or not v['full_document_only'] or v['training_approved'] or v['training_started']:raise ValueError('Worker scope changed')
 return True
def fresh(ids,keys,old_ids,old_keys):
 if len(ids)!=len(set(ids)) or len(keys)!=len(set(keys)):raise ValueError('Repeated fresh document/protocol')
 if set(ids)&set(old_ids) or set(keys)&set(old_keys):raise ValueError('Prior attempted/unknown request must not be reissued')
def idle_card(i,gpus,apps):
 return gpus[i]['memory']<=256 and gpus[i]['util']==0 and not any(a['uuid']==gpus[i]['uuid'] for a in apps)
def verify_payload(P):
 manifest=json.loads((P/'FROZEN_FILES.json').read_text())
 for n,h in manifest.items():
  if sha(P/n)!=h:raise ValueError('Frozen payload differs: '+n)
 x=json.loads((P/'EXCLUSION_PROOF.json').read_text())
 fresh(x['new_body_ids'],x['new_request_keys'],x['old_attempted_body_ids'],x['old_request_keys'])
 if not x['disjoint'] or x['old_unknown_ledger_modified']:raise ValueError('Unknown isolation absent')
 return dict(files=len(manifest),manifest_sha256=sha(P/'FROZEN_FILES.json'),exclusion_sha256=sha(P/'EXCLUSION_PROOF.json'),fresh_documents=len(x['new_body_ids']),old_unknowns_preserved=len(x['preserved_unknown_keys']))

def pressure_values(m,p,si,so):
 reasons=[]
 if m['MemAvailable']<16*1024**3:reasons.append('MemAvailable')
 if m['SwapTotal'] and m['SwapFree']<1024**3:reasons.append('SwapFree')
 if p['some']>1 or p['full']>.2:reasons.append('PSI')
 if si>8*1024**2 or so>1024**2:reasons.append('Swap IO')
 return dict(reasons=reasons,mem_available=m['MemAvailable'],swap_free=m['SwapFree'],swap_total=m['SwapTotal'],si=si,so=so,psi=p)

def pressure():
 import time
 m={k:int(v.split()[0])*1024 for k,v in [x.split(':',1) for x in Path('/proc/meminfo').read_text().splitlines()]}
 p={x.split()[0]:float(x.split()[1].split('=')[1]) for x in Path('/proc/pressure/memory').read_text().splitlines()}
 def vm():return {k:int(v) for k,v in [x.split() for x in Path('/proc/vmstat').read_text().splitlines()]}
 t=time.monotonic();v=vm();time.sleep(.2);w=vm();dt=time.monotonic()-t;page=os.sysconf('SC_PAGE_SIZE')
 return pressure_values(m,p,(w['pswpin']-v['pswpin'])*page/dt,(w['pswpout']-v['pswpout'])*page/dt)

def request_pressure_admission():
 import time
 end=time.monotonic()+3600
 while True:
  v=pressure()
  if not v['reasons']:return v
  if time.monotonic()>end:raise TimeoutError('Pressure deferral deadline; no new request')
  time.sleep(10)

def rolling(rows,multiplier,digest,layer):
 from collections import defaultdict
 if multiplier!=4:raise ValueError('Original 4x/32-per-stratum protocol required')
 grouped=defaultdict(list)
 for r in rows:grouped[layer(r)].append(r)
 return [r for s in sorted(grouped) for r in sorted(grouped[s],key=lambda r:digest(['rolling-v11',r['normalized_sha256']]))[:8*multiplier]],{s:len(v) for s,v in grouped.items()}

def train_route_ok(records,approved):
 if not records or not approved or {r['split'] for r in records}!={'train','validation','test'}:raise ValueError('Incomplete independent train/heldout stock')
 if any(r['split']=='train' and r['stratum'] not in approved for r in records):raise ValueError('Held source stratum cannot enter fast path')
 if len({r['h'] for r in records})!=len(records):raise ValueError('Repeated candidate body')

def settled_terminal(v,selected):
 terminal_ok(v)
 if v['selected']!=selected:raise ValueError('Incomplete full rolling sample')

def receipt_item(name,folder):
 import re
 if not re.fullmatch('qwen129_[a-f0-9]{24}',name):raise ValueError('Wrong version/scope')
 p=Path(folder)
 if p.is_absolute() or '..' in p.parts:raise ValueError('Unsafe relative folder')
 return dict(name=name,kind='source_audit',folder=folder)


def cpu_pressure_values(v):
 # CPU-only cgroups cannot swap. Keep actual memory PSI/IO and RAM headroom.
 reasons=[r for r in v['reasons'] if r!='SwapFree']
 if v['mem_available']<64*1024**3:reasons.append('CPU RAM headroom 64GiB')
 return dict(v,reasons=reasons,scope='CPU_ONLY_SWAP_DISABLED_CGROUP',GPU_request_guard_changed=False)

def cpu_pressure():
 cg=identity(os.getpid())[1]
 if Path('/sys/fs/cgroup'+cg+'/memory.swap.max').read_text().strip()!='0':raise ValueError('CPU admission requires actual cgroup swap.max=0')
 return cpu_pressure_values(pressure())
