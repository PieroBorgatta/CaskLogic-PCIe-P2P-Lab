"""Requalify the published, redacted logs in fresh interpreter processes."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parent
VALIDATORS={'physical-pull':'log_validation','host-source':'host_log_validation','bar0-read':'bar0_log_validation','pramin-push':'pramin_log_validation','aer-report':'aer_log_validation'}
code="""from pathlib import Path
import importlib,json,sys
v=importlib.import_module(sys.argv[1]);p=Path('results')
ccfg={'0000:00:01.0':(0x460d8086,0x04008077),'0000:00:07.0':(0x466e8086,0x0e009077),'0000:00:07.2':(0x462f8086,0x0e009077)}
r=v.validate_log((p/'result.log').read_text(),ccfg,(p/'kernel-research.log').read_text())
assert r['protocol_complete'],r
expected=json.loads((p/'qualified.json').read_text())
assert r==expected, 'Replayed qualification differs'
print(json.dumps({'experiment':Path.cwd().name,'protocol_complete':r['protocol_complete'],'peer_comparisons':r['comparisons'],'peer_failures':r['failures']}))
"""
for name,validator in VALIDATORS.items():
 subprocess.run([sys.executable,'-c',code,validator],cwd=ROOT/name,check=True)
