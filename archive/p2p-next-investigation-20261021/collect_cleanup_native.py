#!/usr/bin/env python3
"""Raccoglie e pulisce soltanto CaskLogicTcssNext, dopo il ritorno a XCP.

Default sola lettura. --collect conserva l'intero albero EFI e tutti i risultati;
--cleanup rimuove la sola voce/cartella registrata, dopo nuova verifica integrale.
Python3.6, nessuna scrittura SPI/PCI, nessun comando VM o reboot.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import time

HERE = Path(__file__).resolve().parent
INSTALLER_SHA = '8d86cfac50fc14ba07b0afa93c72351873088dfe8258a2952faf9c784d7fca30'
source = HERE/'install_native_probe.py'
if hashlib.sha256(source.read_bytes()).hexdigest() != INSTALLER_SHA:
    raise RuntimeError('Installer condiviso diverso dalla versione revisionata')
spec = importlib.util.spec_from_file_location('next_probe_installer',str(source))
i = importlib.util.module_from_spec(spec); spec.loader.exec_module(i)
R = i.R
BACKUP = R/'native-pushpull-esp-backup'
RESULTS = R/'native-pushpull-results'
COLLECTION = R/'native-pushpull-collection.json'
BIG = {'probe-kernel.efi','probe-initrd.img'}
STATE_COPY = 'native-pushpull-state.json'
RAW_MANIFEST = 'collected-sha256.json'
EXPECTED_CONFIGS = {'0000_00_00.0.config','0000_00_01.0.config','0000_00_07.0.config',
                    '0000_00_07.2.config','0000_01_00.0.config','0000_01_00.1.config',
                    '0000_04_00.0.config','0000_05_00.0.config','0000_06_00.0.config',
                    '0000_06_00.1.config','iomem.txt','ioports.txt'}


def tree(root):
    i.require(root.is_dir() and not root.is_symlink(),'Albero assente/non regolare: '+str(root))
    dev=root.stat().st_dev; directories=[]; files={}
    for parent,dirs,names in os.walk(str(root),followlinks=False):
        for name in dirs:
            p=Path(parent)/name
            i.require(not p.is_symlink() and p.stat().st_dev==dev,'Link/mount inatteso')
            directories.append(str(p.relative_to(root)))
        for name in names:
            p=Path(parent)/name;st=p.lstat()
            i.require(stat.S_ISREG(st.st_mode) and st.st_dev==dev,'File speciale/link inatteso')
            files[str(p.relative_to(root))]={'size':st.st_size,'sha256':i.sha(p)}
    return {'directories':sorted(directories),'files':files}


def fsync_tree(root):
    for parent,dirs,names in os.walk(str(root),topdown=False):
        for name in names:
            fd=os.open(str(Path(parent)/name),os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
        fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY)
        try:os.fsync(fd)
        finally:os.close(fd)


def exact_result_names(manifest):
    return {n:v for n,v in manifest['files'].items() if n not in BIG}


def fields(line):
    return dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)',line))


def validate_log(raw):
    """Esito dati5 e dati0 entrambi raccoglibili; validita protocollo separata."""
    end=[fields(x) for x in raw.splitlines() if x.startswith('CE_PROGRAM_END ')]
    i.require(len(end)==1,'Chiusura programma mancante/duplicata')
    end=end[0]
    i.require(end.get('protocol_complete')=='1' and end.get('comparisons')=='24','Protocollo non concluso')
    rc=end.get('rc');i.require(rc in ('0','5'),'RC programma non classificato: '+str(rc))
    fail=int(end['failures']);i.require(0<=fail<=24 and (rc=='0')==(fail==0),'RC e fallimenti incoerenti')
    for marker in ['NATIVE_TEST_RC='+rc,'SCRIPT_RC='+rc,'PROBE_COMPLETED']:
        i.require(raw.splitlines().count(marker)==1,'Marker logger non valido: '+marker)
    i.require(end.get('trace_complete')=='1' and end.get('ce_observed')=='12' and
              end.get('sm_observed')=='12' and end.get('dropped')=='0' and end.get('trace_errors')=='0',
              'Traccia incompleta: conservare area e richiedere raccolta diagnostica dedicata')
    results=[fields(x) for x in raw.splitlines() if x.startswith('CE_DATA_RESULT ')]
    i.require(len(results)==24 and [int(x['id']) for x in results]==list(range(1,25)),'Risultati incompleti/duplicati')
    i.require(sum(x['valid']=='0' for x in results)==fail and all(x['valid'] in ('0','1') for x in results),'Conteggio dati incoerente')
    i.require([x['mode'] for x in results]==['PUSH']*12+['PULL']*12,'Ordine modalita inatteso')
    for uid in ['00000000000000000000000000000001','00000000000000000000000000000002']:
        i.require(any(x.startswith('CE_GPU ') and 'uuid='+uid in x and 'valid=1' in x for x in raw.splitlines()),'Identita GPU assente')
    for bdf,(_,wanted) in i.CCFG.items():
        vals=re.findall(r'^(?:PEG_CCFG|TCSS_CCFG) '+re.escape(bdf[5:])+r' ([0-9a-f]+)$',raw,re.M)
        i.require(len(vals)==3 and all(int(v,16)==wanted for v in vals),'CCFG nel log non originale')
    return {'program_rc':int(rc),'failures':fail,'comparisons':24,'trace_complete':True,
            'data_all_comparisons_pass':fail==0,'P2P_solution_claimed':False,'direct_route_proven':False}


def observations():
    baseline,ccfg=i.host_preflight();state=i.read_json(i.STATE)
    i.require(state['stage']=='armed','Stato non armed')
    boot=i.run(['efibootmgr','-v']);entries=i.parse_boot(boot)
    i.verify_new_entry(entries,state['original_entries'],state['entry'])
    i.require(state['baseline_sha256']==baseline['sha256'] and state['kernel_args']==i.ARGS and
              state['label']==i.LABEL and state['loader']==i.LOADER,'Stato identita/baseline cambiato')
    package=i.verify_package()
    i.require(state['files']==package['files'] and state['metadata_sha256']==package['metadata_sha256'],'Pacchetto diverso dallo stage')
    manifest=tree(i.DST)
    expected=set(i.PACKAGE_NAMES)|{'result.log','kernel.log'}|{'before-driver/'+n for n in EXPECTED_CONFIGS}
    i.require(set(manifest['files'])==expected and manifest['directories']==['before-driver'],'Albero EFI inatteso: preservare senza pulire')
    for n,digest in dict(package['files'],**package['metadata_sha256']).items():
        i.require(manifest['files'][n]['sha256']==digest,'Payload/metadata EFI cambiato: '+n)
    i.require((i.DST/'IDENTITY.txt').read_bytes()==i.IDENTITY,'Identita directory diversa')
    result=validate_log((i.DST/'result.log').read_text())
    i.require((i.DST/'kernel.log').stat().st_size>0,'Log kernel vuoto')
    return {'baseline':baseline,'ccfg':ccfg,'state':state,'state_sha256':i.sha(i.STATE),
            'boot':boot,'entries':entries,'tree':manifest,'result':result}


def verify_collection(obs):
    c=i.read_json(COLLECTION)
    i.require(c['status']=='collected_verified','Raccolta non conclusa o cleanup gia avviato')
    i.require(c['tree']==obs['tree'] and c['state_sha256']==obs['state_sha256'],'ESP/stato cambiati dopo raccolta')
    i.require(tree(BACKUP)==c['tree'],'Backup completo diverso')
    raw=exact_result_names(c['tree']);i.require(len(raw)==17,'Numero raw inatteso')
    actual=tree(RESULTS)
    i.require(set(actual['files'])==set(raw)|{STATE_COPY,RAW_MANIFEST} and actual['directories']==c['tree']['directories'],'Raccolta file inattesa')
    for n,v in raw.items():i.require(actual['files'][n]==v,'Risultato copiato diverso: '+n)
    i.require(i.sha(RESULTS/STATE_COPY)==c['state_sha256'],'Stato copiato diverso')
    i.require(i.read_json(RESULTS/RAW_MANIFEST)=={n:v['sha256'] for n,v in raw.items()},'Manifest risultati diverso')
    return c


def collect(obs):
    i.require(not BACKUP.exists() and not RESULTS.exists() and not COLLECTION.exists(),'Raccolta preesistente: non sovrascrivere')
    size=sum(x['size'] for x in obs['tree']['files'].values())+sum(x['size'] for x in exact_result_names(obs['tree']).values())+32*1024*1024
    i.require(shutil.disk_usage(str(R)).free>size,'Spazio insufficiente per conservazione integrale')
    c={'status':'collect_pending','epoch':time.time(),'tree':obs['tree'],'state_sha256':obs['state_sha256'],
       'baseline_sha256':obs['baseline']['sha256'],'original_files':obs['baseline']['baseline']['original_files'],
       'boot_before':obs['boot'],'ccfg_before':obs['ccfg'],'entry':obs['state']['entry'],'result':obs['result'],
       'backup':str(BACKUP),'results':str(RESULTS),'installer_sha256':INSTALLER_SHA,'collector_sha256':i.sha(Path(__file__)),
       'mutations':[]}
    i.atomic_json(COLLECTION,c)
    shutil.copytree(str(i.DST),str(BACKUP));fsync_tree(BACKUP)
    i.require(tree(BACKUP)==obs['tree'] and tree(i.DST)==obs['tree'],'Backup/source diversi durante copia')
    RESULTS.mkdir()
    for directory in obs['tree']['directories']:(RESULTS/directory).mkdir()
    raw=exact_result_names(obs['tree'])
    for n,v in raw.items():i.copy_verified(BACKUP/n,RESULTS/n,v['sha256'])
    i.copy_verified(i.STATE,RESULTS/STATE_COPY,obs['state_sha256'])
    i.atomic_json(RESULTS/RAW_MANIFEST,{n:v['sha256'] for n,v in raw.items()})
    fsync_tree(RESULTS);os.sync()
    after=observations()
    i.require(after['tree']==obs['tree'] and after['state_sha256']==obs['state_sha256'] and
              after['boot']==obs['boot'] and after['ccfg']==obs['ccfg'],'Stato cambiato durante raccolta')
    c.update(status='collected_verified',epoch_collected=time.time(),boot_after_collect=after['boot'],
             ccfg_after_collect=after['ccfg'],full_backup_files=len(obs['tree']['files']),raw_result_files=len(raw),
             additional_state_files=1,original_boot_files_unchanged=True)
    i.atomic_json(COLLECTION,c);verify_collection(after);os.sync()
    return c


def cleanup(obs,c):
    # Tutti i backup completi vengono ricalcolati prima di ogni rimozione.
    verify_collection(obs);i.verify_baseline();i.read_ccfg()
    i.require(i.parse_boot(i.run(['efibootmgr','-v']))==obs['entries'],'Boot cambiato prima cleanup')
    c.update(status='cleanup_entry_pending',epoch_cleanup=time.time());i.atomic_json(COLLECTION,c)
    entry=obs['state']['entry']
    i.require(entry not in ('0000','0001'),'Voce originale non eliminabile')
    i.run(['efibootmgr','--bootnum',entry,'--delete-bootnum'])
    after=i.run(['efibootmgr','-v']);i.require(i.parse_boot(after)==obs['state']['original_entries'],'Voci originali alterate')
    c['mutations'].append({'entry_removed':entry});c['status']='cleanup_directory_pending';i.atomic_json(COLLECTION,c)
    i.require(tree(BACKUP)==obs['tree'] and tree(i.DST)==obs['tree'],'Backup/ESP cambiato prima rimozione directory')
    i.verify_baseline();i.read_ccfg()
    shutil.rmtree(str(i.DST));i.require(not i.DST.exists(),'Directory non rimossa')
    c['mutations'].append({'directory_removed':'CaskLogicTcssNext'})
    final=i.run(['efibootmgr','-v']);i.require(i.parse_boot(final)==obs['state']['original_entries'],'Voci originali diverse dopo cleanup')
    i.verify_baseline();ccfg=i.read_ccfg();i.require(tree(BACKUP)==obs['tree'],'Backup diverso dopo cleanup')
    c.update(status='cleanup_verified',epoch_completed=time.time(),boot_after_cleanup=final,ccfg_final=ccfg,
             original_boot_files_unchanged=True,full_backup_preserved=True)
    i.atomic_json(COLLECTION,c);os.sync();return c


def main():
    parser=argparse.ArgumentParser(description=__doc__);group=parser.add_mutually_exclusive_group()
    group.add_argument('--collect',action='store_true');group.add_argument('--cleanup',action='store_true')
    args=parser.parse_args();obs=observations()
    if args.collect:c=collect(obs)
    elif args.cleanup:c=cleanup(obs,verify_collection(obs))
    else:
        if COLLECTION.exists():verify_collection(obs)
        print(json.dumps({'status':'verified_read_only','backup_exists':BACKUP.exists(),'files':len(obs['tree']['files']),
                          'program_result':obs['result'],'entry':obs['state']['entry'],'ccfg':obs['ccfg']}));return
    print(json.dumps({'status':c['status'],'backup':str(BACKUP),'results':str(RESULTS),'program_result':c['result']}))


if __name__=='__main__':main()
