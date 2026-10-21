"""Verify the public package, not private originals or historical manifest hashes."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    manifest=json.loads((ROOT/'provenance/SHA256SUMS.json').read_text())
    errors=[]
    for rel,expected in manifest['files'].items():
        p=ROOT/rel
        if not p.is_file() or p.is_symlink():errors.append(rel+': missing or symlink');continue
        data=p.read_bytes()
        if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:errors.append(rel+': hash/size mismatch')
    print(json.dumps({'status':'FAIL' if errors else 'PASS','checked_files':len(manifest['files']),'errors':errors},indent=2))
    return bool(errors)
if __name__=='__main__':raise SystemExit(main())
