"""Reanalyze the published native PUSH/PULL log; no GPU or remote access."""
import importlib.util, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'archive/p2p-next-investigation-20261021'
def main():
    spec=importlib.util.spec_from_file_location('historical_analyzer',BASE/'native-pushpull-probe/analyze_ce.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    result=mod.audit((BASE/'native-pushpull-results/result.log').read_text())
    assert result['comparisons']==24 and result['data_failures']==18
    assert result['ce_observed']==12 and result['sm_observed']==12 and result['trace_complete']
    assert result['direct_route_proven'] is False
    for case in result['cases']:
        expected=case['mode']=='PUSH' and case['source']==1 and case['destination']==0
        assert case['data_valid']==expected, case
    print(json.dumps({'offline_replay':'PASS','comparisons':24,'data_failures':18,'ce_observed':12,'sm_observed':12,'hardware_fixed':False,'hardware_operations':False},indent=2))
if __name__=='__main__': main()
