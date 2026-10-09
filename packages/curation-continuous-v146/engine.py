"""One coordinator reserves/writes; async execution refills without a group barrier."""
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
import time

def refill(jobs,prepare,execute,finish,workers,admit=lambda:True,idle_limit=None):
 if workers not in (1,2,4,8,16,32):raise ValueError('Bounded tested window required')
 iterator=iter(jobs);active={};exhausted=False;stopped=False;completed=0;peak=0;started=time.monotonic();idle_started=started
 with ThreadPoolExecutor(max_workers=workers) as pool:
  while active or not exhausted and not stopped:
   while not exhausted and not stopped and len(active)<workers and admit():
    try:j=next(iterator)
    except StopIteration:exhausted=True;break
    task=prepare(j)
    if task is not None:active[pool.submit(execute,task)]=task;peak=max(peak,len(active))
   if not active:
    if exhausted or stopped:break
    if idle_limit is not None and time.monotonic()-idle_started>idle_limit:raise TimeoutError('Pressure admission deadline; no new request')
    time.sleep(.1);continue
   done,_=wait(active,timeout=.5,return_when=FIRST_COMPLETED)
   # Drain all completions before reserving replacements. Unknown stops NEW work only.
   for f in done:
    task=active.pop(f)
    if not finish(task,f.result()):stopped=True
    completed+=1;idle_started=time.monotonic()
 elapsed=time.monotonic()-started
 return dict(workers=workers,peak_inflight=peak,completed=completed,elapsed_seconds=elapsed,annotations_per_second=completed/max(elapsed,1e-9),stop_reason='unknown_local_response_no_auto_retry' if stopped else None,group_barrier=False)
