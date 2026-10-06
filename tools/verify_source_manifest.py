"""Verify the public review snapshot bytes; no runtime or network actions."""
from pathlib import Path
import hashlib,json,ast
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'SOURCE_MANIFEST.json').read_text())
for name,entry in manifest['files'].items():
 p=root/name
 assert hashlib.sha256(p.read_bytes()).hexdigest()==entry['published_sha256'],name
 if p.suffix=='.py':ast.parse(p.read_text(),filename=name)
 if p.suffix=='.json':json.loads(p.read_text())
print(f"Verified {len(manifest['files'])} public source/template files")
