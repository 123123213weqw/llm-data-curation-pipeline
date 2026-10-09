"""Explicit original parser runtime for every CPU gate, including startup references."""
import sys,os
from pathlib import Path
def bootstrap(cfg):
 deps=Path(cfg['runtime_dependencies']);code=Path(cfg['code'])
 if not deps.is_dir() or not code.is_dir():raise ValueError('Bound original CPU runtime missing')
 sys.path[:0]=[str(deps),str(code/'src'),str(code/'scripts')];os.environ['PYTHONPATH']=str(deps)
 return deps
