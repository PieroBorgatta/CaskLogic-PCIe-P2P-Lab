"""Reconstruct the documented OEM-derived candidate as a regular file. Never flash."""
import argparse, hashlib, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def digest(data): return hashlib.sha256(data).hexdigest()
def rebuild(base, region, manifest):
    v = next(v for v in manifest['variants'] if v['variant'] == 'peg-tcss-d1-d7')
    if len(base) != manifest['base_bytes'] or digest(base) != manifest['base_sha256']:
        raise ValueError('Exact OEM 1.26 preimage required; hash or size mismatch')
    start, count = v['offset_in_oem'], v['region_bytes']
    if len(region) != count or digest(region) != v['candidate_region_sha256']:
        raise ValueError('Candidate region hash or size mismatch')
    if digest(base[start:start+count]) != v['original_region_sha256']:
        raise ValueError('Original region mismatch')
    output = base[:start] + region + base[start+count:]
    if digest(output) != v['full_image_sha256']:
        raise ValueError('Output image hash mismatch')
    return output

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('oem_image',type=Path); ap.add_argument('output',type=Path)
    args=ap.parse_args()
    if not args.oem_image.is_file(): ap.error('Input must be a regular file')
    if args.output.exists() or args.output.is_symlink(): ap.error('Output already exists; refusing overwrite')
    manifest=json.loads((ROOT/'firmware/manifest.json').read_text())
    try: data=rebuild(args.oem_image.read_bytes(), (ROOT/'firmware/regions/peg-tcss-d1-d7.bin').read_bytes(), manifest)
    except ValueError as exc: ap.error(str(exc))
    with args.output.open('xb') as f: f.write(data)
    print(json.dumps({'status':'REBUILT_OFFLINE','sha256':digest(data),'bytes':len(data),'hardware_operations':False}))
if __name__=='__main__': main()
