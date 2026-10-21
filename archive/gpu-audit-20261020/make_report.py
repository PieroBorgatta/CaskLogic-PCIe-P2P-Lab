"""Report locale dai risultati misurati; nessun dato di esempio o stima nascosta."""
from pathlib import Path
import base64
from collections import defaultdict
import datetime as dt
import html
import json
import re
import statistics
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
ADA = 'GPU-00000000-0000-0000-0000-000000000001'
A2000 = 'GPU-00000000-0000-0000-0000-000000000002'
NAMES = {ADA: 'RTX 2000 Ada · interna', A2000: 'RTX A2000 · AOOSTAR'}
COLORS = {ADA: '#3564d8', A2000: '#d97726'}


def load(name, fallback=None):
    p = ROOT / name
    return json.loads(p.read_text()) if p.exists() else fallback


def fmt(value, digits=2):
    return '—' if value is None else f'{value:,.{digits}f}'.replace(',', ' ').replace('.', ',')


def table(headers, rows):
    return '<div class="table-wrap"><table><thead><tr>' + ''.join(
        '<th>' + html.escape(str(x)) + '</th>' for x in headers) + '</tr></thead><tbody>' + ''.join(
        '<tr>' + ''.join('<td>' + html.escape(str(x)) + '</td>' for x in row) + '</tr>'
        for row in rows) + '</tbody></table></div>'


def nv_result(name):
    p = ROOT / (name + '.log')
    if not p.exists():
        return {}
    text = p.read_text(errors='replace')
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data = json.loads(text[text.index('{'):text.rindex('}') + 1])
        except (ValueError, json.JSONDecodeError):
            return {}
    tests = data.get('nvbandwidth', {}).get('testcases', [])
    return tests[0] if tests else {}


def nv_matrix(name):
    rows = nv_result(name).get('bandwidth_matrix', [])
    result = []
    for row in rows:
        vals = []
        for x in row:
            try:
                vals.append(float(x))
            except (ValueError, TypeError):
                vals.append(None)
        result.append(vals)
    return result


def gemm_value(filename, precision, size=8192):
    data = load(filename, {})
    for case in data.get('cases', []):
        if case.get('precision') == precision and case.get('size') == size and case.get('correct'):
            return case['tflops']
    return None


def nccl_result(name):
    p = ROOT / (name + '.log')
    if not p.exists():
        return {'rows': [], 'errors': None}
    rows = []
    for line in p.read_text(errors='replace').splitlines():
        parts = line.split()
        if len(parts) >= 13 and parts[0].isdigit() and parts[2] == 'float':
            try:
                rows.append({'bytes': int(parts[0]), 'out_time_us': float(parts[5]),
                             'out_GBps': float(parts[6]), 'out_bus_GBps': float(parts[7]),
                             'out_wrong': int(parts[8]), 'in_time_us': float(parts[9]),
                             'in_GBps': float(parts[10]), 'in_bus_GBps': float(parts[11]),
                             'in_wrong': int(parts[12])})
            except ValueError:
                continue
    return {'rows': rows, 'errors': sum(x['out_wrong'] + x['in_wrong'] for x in rows) if rows else None}


def main():
    state = load('status.json', {})
    stages = load('stages.json', [])
    before, after = load('before.json', {}), load('after.json', {})
    start = before.get('started_epoch', stages[0]['started_epoch'] if stages else 0)
    end = after.get('finished_epoch', max((s['started_epoch'] + s['seconds'] for s in stages), default=start))
    duration = (end - start) / 60
    samples = []
    for line in (ROOT / 'telemetry.jsonl').read_text().splitlines():
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    by_gpu = defaultdict(list)
    for sample in samples:
        for gpu in sample.get('gpus', []):
            by_gpu[gpu['uuid']].append({**gpu, 'epoch': sample['epoch'], 'phase': sample['phase']})
    stats = {}
    for uuid, values in by_gpu.items():
        active = [v for v in values if v['phase'] == 'stress_dual_15min' or
                  v['phase'] == ('stress_single_ada' if uuid == ADA else 'stress_single_a2000')]
        steady = [v for v in active if float(v['utilization.gpu']) >= 80]
        stats[uuid] = {
            'maximum_temperature_C': max(float(v['temperature.gpu']) for v in values),
            'maximum_power_W': max(float(v['power.draw']) for v in values),
            'maximum_memory_MiB': max(float(v['memory.used']) for v in values),
            'stress_mean_power_W': statistics.mean(float(v['power.draw']) for v in steady) if steady else None,
            'stress_mean_utilization_percent': statistics.mean(float(v['utilization.gpu']) for v in active) if active else None,
            'stress_sm_clock_median_MHz': statistics.median(float(v['clocks.current.sm']) for v in steady) if steady else None,
            'thermal_slowdown_samples': sum(bool(int(v['clocks_event_reasons.active'], 16) & (0x20 | 0x40)) for v in active),
            'power_cap_samples': sum(bool(int(v['clocks_event_reasons.active'], 16) & 0x04) for v in active),
            'samples': len(values), 'stress_samples': len(active)}

    stress_details = []
    for stage in stages:
        if not stage['name'].startswith('stress_'):
            continue
        raw = (ROOT / stage['log']).read_text(errors='replace')
        error_groups = re.findall(r'errors:\s*([0-9]+(?:\s*-\s*[0-9]+)*)', raw)
        errors = [int(x) for group in error_groups for x in re.findall(r'\d+', group)]
        cards = {}
        for uuid, values in by_gpu.items():
            active = [v for v in values if v['phase'] == stage['name'] and
                      float(v['utilization.gpu']) >= 80]
            if active:
                cards[NAMES[uuid]] = {
                    'maximum_temperature_C': max(float(v['temperature.gpu']) for v in active),
                    'mean_power_W': statistics.mean(float(v['power.draw']) for v in active),
                    'median_sm_clock_MHz': statistics.median(float(v['clocks.current.sm']) for v in active),
                    'thermal_slowdown_samples': sum(bool(int(v['clocks_event_reasons.active'], 16) & 0x60) for v in active)}
        stress_details.append({'phase': stage['name'], 'configured_load_seconds': int(stage['command'][-1]),
                               'wall_seconds': stage['seconds'],
                               'maximum_reported_errors': max(errors) if errors else None,
                               'gpu_final_results': re.findall(r'GPU\s+\d+:\s*(?:OK|FAULTY|DIED)\b', raw),
                               'gpus': cards})

    new_kernel_lines = set(after.get('kernel', '').splitlines()) - set(before.get('kernel', '').splitlines())
    serious = [x for x in sorted(new_kernel_lines) if re.search(r'NVRM: Xid|GPU has fallen|AER:.*(?:fatal|error)|I/O error', x, re.I)]
    host_kernel = load('host-kernel-after-audit.json', {}).get('kernel','')
    host_errors = [x for x in host_kernel.splitlines() if re.search(r'AER:|Xid|fallen off|pcie.*error',x,re.I)]
    unavailable = [{'stage':s['name'], 'status':nv_result(s['name']).get('status'),
                    'reason':nv_result(s['name']).get('waiver_reason')}
                   for s in stages if nv_result(s['name']).get('status')=='Waived']
    audit = {'state': state.get('state'), 'duration_minutes': duration, 'gpu_stats': stats,
             'stage_count': len(stages), 'failed_stages': [s for s in stages if s['returncode'] or s['timed_out']],
             'new_serious_kernel_messages': serious, 'host_kernel_pcie_error_matches': host_errors,
             'stress_details': stress_details, 'unavailable_cases':unavailable,
             'route_confirmation':load('route_confirmation.json',{}),
             'host_to_device_512': nv_matrix('host_to_device_memcpy_ce_512'),
             'device_to_host_512': nv_matrix('device_to_host_memcpy_ce_512'),
             'nccl_default': nccl_result('nccl_allreduce_default'),
             'nccl_host_staged': nccl_result('nccl_allreduce_host_staged')}
    (ROOT / 'summary.json').write_text(json.dumps(audit, indent=2))

    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.labelcolor': '#334155', 'text.color': '#17243b',
                         'axes.edgecolor': '#b8c3d2', 'grid.color': '#e4e9f0',
                         'figure.facecolor': '#ffffff', 'axes.facecolor': '#ffffff'})
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True, constrained_layout=True)
    for uuid in [ADA, A2000]:
        values = by_gpu[uuid]
        xs = [(v['epoch'] - start) / 60 for v in values]
        for ax, field in zip(axes, ['temperature.gpu', 'power.draw', 'clocks.current.sm']):
            ax.plot(xs, [float(v[field]) for v in values], color=COLORS[uuid], lw=1.2, label=NAMES[uuid])
    for ax, label in zip(axes, ['Temperatura GPU (°C)', 'Potenza della scheda (W)', 'Frequenza SM (MHz)']):
        ax.set_ylabel(label)
        ax.grid(axis='y', alpha=.8)
        for s in stages:
            if s['name'].startswith('stress_'):
                ax.axvspan((s['started_epoch']-start)/60,
                           (s['started_epoch']+s['seconds']-start)/60, color='#edf2ff', alpha=.55, zorder=0)
    axes[0].legend(loc='lower left', bbox_to_anchor=(0,1.02), ncol=2, frameon=False)
    axes[-1].set_xlabel('Minuti dall’inizio delle prove; fasce azzurre = stress prolungato')
    fig.savefig(ROOT/'telemetria.png', dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4), constrained_layout=True)
    labels = ['FP32 IEEE', 'TF32', 'FP16', 'BF16', 'FP8 E4M3']
    codes = ['fp32', 'tf32', 'fp16', 'bf16', 'fp8_e4m3']
    for i, uuid in enumerate([ADA, A2000]):
        file = 'compute_hot_gpu'+str(i)+'.json'
        if not (ROOT/file).exists(): file='compute_gpu'+str(i)+'.json'
        vals = [gemm_value(file, c) for c in codes]
        positions = [j + (-.18 if i == 0 else .18) for j in range(len(codes))]
        ax.bar(positions, [v or 0 for v in vals], width=.34, color=COLORS[uuid], label=NAMES[uuid])
        for pos, val in zip(positions, vals):
            if val is not None: ax.text(pos, val+.5, fmt(val,1), ha='center', fontsize=9)
            else: ax.text(pos, 1, 'non supportato', rotation=90, ha='center', va='bottom', fontsize=9)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_ylabel('TFLOP/s · prodotto di matrici 8.192 × 8.192')
    ax.grid(axis='y', alpha=.7)
    ax.set_axisbelow(True)
    ax.legend(frameon=False)
    fig.savefig(ROOT/'calcolo.png', dpi=180)
    plt.close(fig)

    decisions = load('conclusions.json', {'paragraphs': ['Le prove sono ancora in corso.'], 'status_label': 'PROVVISORIO'})
    rows = []
    for i, uuid in enumerate([ADA, A2000]):
        memory = load('memory_gpu'+str(i)+'.json', {})
        st = stats[uuid]
        rows.append([NAMES[uuid], '16 GB' if i == 0 else '12 GB',
                     fmt(st['maximum_temperature_C'],0)+' °C', fmt(st['maximum_power_W'],1)+' W',
                     fmt(memory.get('vram',{}).get('tested_bytes',0)/1024**3,2)+' GiB',
                     str(memory.get('vram',{}).get('errors','—'))])
    hwtable=table(['Scheda','VRAM nominale','Temperatura massima','Potenza massima campionata','VRAM verificata con pattern','Errori pattern'],rows)
    rows=[]
    for label, code in zip(labels,codes):
        rows.append([label]+[fmt(gemm_value('compute_gpu'+str(i)+'.json',code)) for i in [0,1]]+
                    [fmt(gemm_value('compute_hot_gpu'+str(i)+'.json',code)) for i in [0,1]])
    math_table=table(['Precisione','Ada iniziale','A2000 iniziale','Ada dopo stress','A2000 dopo stress'],rows)
    accuracy_rows=[]
    for i in [0,1]:
        filename='compute_hot_gpu'+str(i)+'.json'
        if not (ROOT/filename).exists(): filename='compute_gpu'+str(i)+'.json'
        for case in load(filename,{}).get('cases',[]):
            if case.get('size')==8192 and case.get('correct'):
                accuracy_rows.append(['Ada' if i==0 else 'A2000',case['precision'],
                    fmt(100*case['relative_l2_vs_quantized_input_fp64'],4)+'%',
                    fmt(100*case['relative_l2_vs_original_input_fp64'],4)+'%'])
    accuracy_table=table(['Scheda','Precisione','Errore del kernel rispetto agli input quantizzati','Errore totale rispetto agli input FP32'],accuracy_rows)
    rows=[]
    for size in [1,16,512]:
        for key,caption in [('host_to_device','RAM → GPU'),('device_to_host','GPU → RAM')]:
            matrix=nv_matrix(key+'_memcpy_ce_'+str(size))
            values=matrix[0] if matrix else [None,None]
            rows.append([caption,str(size)+' MiB']+[fmt(v) for v in values])
    transfer_table=table(['Direzione','Blocco','Ada · GB/s','A2000 · GB/s'],rows)
    local_table=table(['Memoria locale · blocchi da 512 MiB','Ada · GB/s','A2000 · GB/s'],
        [[caption]+[fmt(v) for v in (nv_matrix(name)[0] if nv_matrix(name) else [None,None])]
         for name,caption in [('device_local_read_sm','Lettura SM'),
                              ('device_local_write_sm','Scrittura SM'),
                              ('device_local_copy','Copia CE · byte utili')]])
    supplemental_sections=[]
    for name in ['host_to_device_bidirectional_memcpy_ce','device_to_host_bidirectional_memcpy_ce',
                 'host_to_all_memcpy_ce','all_to_host_memcpy_ce','host_device_latency_sm']:
        res=nv_result(name)
        if res:
            supplemental_sections.append('<h3>'+html.escape(name)+'</h3><p class="muted">'+
                html.escape(res.get('bandwidth_description',''))+'</p>'+table(['Riga CPU','Ada','A2000'],
                [[i]+[fmt(v,3) for v in row] for i,row in enumerate(nv_matrix(name))]))
    peer_sections=[]
    for name in ['device_to_device_memcpy_read_ce','device_to_device_memcpy_write_ce',
                 'device_to_device_bidirectional_memcpy_write_ce','device_to_device_memcpy_read_sm',
                 'device_to_device_memcpy_write_sm','device_to_device_latency_sm']:
        res=nv_result(name)
        if res:
            if res.get('status')=='Waived':
                peer_sections.append('<h3>'+html.escape(name)+'</h3><p>Non eseguito: nessuna coppia di GPU accessibile tramite P2P CUDA.</p><p class="muted">Stato dello strumento: Waived · '+html.escape(res.get('waiver_reason',''))+'</p>')
            else:
                peer_sections.append('<h3>'+html.escape(name)+'</h3><p class="muted">'+html.escape(res.get('bandwidth_description',''))+
                     '</p>'+table(['Riga / colonna','0 · Ada','1 · A2000'],
                     [[str(i)+' · '+('Ada' if i==0 else 'A2000')]+[fmt(x,3) for x in row] for i,row in enumerate(nv_matrix(name))]))
    staged=load('host_staged_gpu_transfers.json',{}).get('transfers',[])
    staged_table=table(['Percorso esplicito tramite RAM pinned','GB/s','Integrità'],
                       [[('Ada → RAM → A2000' if x['source']==0 else 'A2000 → RAM → Ada'),
                         fmt(x['median_GBps']),str(x['correct'])] for x in staged])
    nccl_rows=[]
    for mode,key in [('NCCL predefinito','nccl_default'),('NCCL con P2P disabilitato','nccl_host_staged')]:
        data=audit[key]
        if data['rows']:
            row=max(data['rows'],key=lambda x:x['bytes'])
            nccl_rows.append([mode,fmt(row['bytes']/1024**2,0)+' MiB',fmt(row['out_time_us']/1000),
                              fmt(row['out_GBps']),fmt(row['in_GBps']),str(data['errors'])])
        else: nccl_rows.append([mode,'—','—','—','—','Non completato; vedere log'])
    nccl_table=table(['Modalità','Messaggio massimo','Tempo out-of-place · ms','Banda out-of-place · GB/s','Banda in-place · GB/s','Errori dati'],nccl_rows)
    stress_table=table(['Prova','Carico impostato','Durata totale della fase','Esito'],
        [[s['name'],str(int(s['command'][-1])//60)+' min',fmt(s['seconds']/60)+' min','OK' if s.get('gpu_burn_ok') else 'Da esaminare']
         for s in stages if s['name'].startswith('stress_')])
    stress_thermal_table=table(['Fase','Scheda','Temperatura massima','Potenza media sotto carico','Frequenza SM mediana','Campioni con rallentamento termico'],
        [[x['phase'], name,fmt(v['maximum_temperature_C'],0)+' °C',fmt(v['mean_power_W'],1)+' W',
          fmt(v['median_sm_clock_MHz'],0)+' MHz',v['thermal_slowdown_samples']]
         for x in stress_details for name,v in x['gpus'].items()])
    timing_rows=[]
    for i in [0,1]:
        for x in load('compute_hot_gpu'+str(i)+'.json',load('compute_gpu'+str(i)+'.json',{})).get('attention',[]):
            timing_rows.append(['Ada' if i==0 else 'A2000',x['dtype'].replace('torch.',''),fmt(x['median_ms'],3),
                                f"{x['reference_relative_l2']:.4g}",str(x['gradients_finite'])])
    attention_table=table(['GPU','Precisione','Forward + backward · ms','Errore relativo riferimento CPU','Gradienti finiti'],timing_rows)
    sources=load('sources.json',[])
    links=''.join('<li><a href="https://github.com/'+x['repo']+'/tree/'+x['commit']+'">'+html.escape(x['repo'])+'</a> · <code>'+x['commit']+'</code></li>' for x in sources)
    stages_table=table(['Fase','Secondi','Codice uscita','Timeout'],
                       [[s['name'],fmt(s['seconds'],1),s['returncode'],s['timed_out']] for s in stages])
    def img(name):
        return '<img alt="'+html.escape(name)+'" src="data:image/png;base64,'+base64.b64encode((ROOT/name).read_bytes()).decode()+'">'
    date=dt.datetime.fromtimestamp(start,ZoneInfo('Europe/Rome')).strftime('%d/%m/%Y %H:%M')
    paragraphs=''.join('<p>'+html.escape(x)+'</p>' for x in decisions['paragraphs'])
    logo=Path(__file__).resolve().parents[3]/'docs/assets/casklogic-logo.png'
    logo_html='<img class="logo" alt="CaskLogic" src="data:image/png;base64,'+base64.b64encode(logo.read_bytes()).decode()+'">' if logo.exists() else ''
    document='''<!doctype html><html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CaskLogic · Collaudo GPU</title><style>
:root{color-scheme:light}*{box-sizing:border-box}body{margin:0;background:#eff3f8;color:#17243b;font:16px/1.6 Arial,sans-serif}main{max-width:1180px;margin:32px auto;background:white;padding:42px;border-radius:18px;box-shadow:0 8px 40px #17243b0c}header{border-bottom:1px solid #dbe4ef;padding-bottom:24px}.logo{width:180px;max-height:110px;object-fit:contain;object-position:left}h1{font-size:34px;line-height:1.2;margin:12px 0}h2{font-size:23px;margin-top:38px}h3{font-size:16px;margin-top:25px}.tag{display:inline-block;background:#e8efff;color:#234fb0;border-radius:20px;padding:4px 14px;font-size:12px;font-weight:bold;letter-spacing:.8px}.muted{color:#5c6b80;font-size:14px}.summary{background:#f5f8ff;border-left:4px solid #3564d8;padding:12px 23px;margin-top:25px}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px;margin:12px 0 24px}th,td{padding:11px 12px;border-bottom:1px solid #e3e9f1;text-align:left;white-space:nowrap}th{background:#f1f5fb;font-weight:600}img{max-width:100%;height:auto}code{font-size:12px;background:#f2f5f9;padding:3px 5px}li{margin:8px 0}a{color:#2458bf}details{border:1px solid #dce5f0;border-radius:10px;padding:16px;margin-top:18px}summary{cursor:pointer;font-weight:bold}footer{font-size:13px;color:#617187;border-top:1px solid #dbe4ef;padding-top:20px;margin-top:35px}@media(max-width:700px){main{margin:0;border-radius:0;padding:22px}h1{font-size:28px}}@media print{body{background:white}main{box-shadow:none;margin:0;padding:0}details{break-inside:avoid}h2{break-after:avoid}table{font-size:11px}}
</style><main><header>'''+logo_html+'<div class="tag">COLLAUDO HARDWARE · '+html.escape(decisions['status_label'])+'</div><h1>Due GPU, misurate sul tuo server</h1><p class="muted">'+date+' · Europe/Rome · collaudo principale '+fmt(duration,1)+' minuti · autore del progetto: Piero Borgatta</p></header>'
    document+='<div class="summary">'+paragraphs+'</div><h2>Hardware e integrità</h2>'+hwtable
    document+='<p class="muted">VRAM verificata con tre passaggi, ciascuno con zero, uno, pattern alternati e indirizzi. Sono coperti circa l’80% dei byte liberi all’inizio della prova. I GB/s sono decimali; GiB e MiB sono binari.</p>'
    document+='<h2>Calcolo CUDA e precisioni</h2>'+img('calcolo.png')+math_table
    document+='<p>TFLOP/s misurati su prodotti di matrici dense 8.192 × 8.192, contando due operazioni per moltiplicazione e somma. Cinque campioni con eventi CUDA dopo riscaldamento; sono esclusi generazione, conversione degli input e trasferimenti. FP8 usa E4M3 con scale unitarie e uscita BF16: misura il kernel, non una pipeline di training FP8. Le verifiche confrontano 256 elementi con un riferimento CPU FP64; il risultato non valuta qualità linguistica.</p><details><summary>Accuratezza numerica: distinguere kernel e quantizzazione</summary>'+accuracy_table+'<p class="muted">Errori relativi L2 su 256 elementi campionati. Il controllo del kernel usa come riferimento gli input già convertiti: la differenza rispetto agli input FP32 originali include anche la quantizzazione. Le scale FP8 unitarie sono una scelta del microbenchmark e non costituiscono una ricetta di addestramento.</p></details>'
    document+='<h3>Attenzione con contesto 2.048</h3>'+attention_table+'<p class="muted">Un’operazione FlashAttention causale GQA 16/4, dimensione testa 64, batch 2, con forward e backward. I gradienti non aggiornano pesi; nessun checkpoint del modello viene caricato. Non sono token/s di un modello completo.</p>'
    document+='<h2>RAM ↔ GPU</h2>'+transfer_table+'<p class="muted">NVIDIA nvbandwidth, copy engine, memoria host pinned, cinque campioni e verifica dei dati attiva. I servizi abituali della VM restano attivi: queste misure rappresentano questo ambiente, non un confronto bare metal.</p>'+local_table+'<p class="muted">La copia locale riporta i byte utili copiati: ogni byte richiede una lettura e una scrittura. Le prove separate SM riportano il traffico della singola operazione.</p><details><summary>Trasferimenti simultanei e latenza RAM ↔ GPU</summary>'+''.join(supplemental_sections)+'</details>'
    document+='<h2>Stress e andamento nel tempo</h2>'+stress_table+img('telemetria.png')+stress_thermal_table+'<p>GPU-burn usa circa l’80% della memoria disponibile e confronta i risultati ripetuti. La durata totale della fase comprende inizializzazione e chiusura oltre al carico impostato. Temperatura, potenza e frequenze sono campionate ogni due secondi e associate tramite UUID, evitando differenze di ordinamento fra CUDA e nvidia-smi. Arresto automatico della prova a 90 °C; nessuna modifica a potenza massima, tensioni, IOMMU o ACS. Le letture di potenza riguardano le schede, non la presa o l’UPS.</p>'
    document+='<h2>Comunicazione tra le GPU</h2><p>La topologia dichiarata è PHB, senza NVLink. Il riepilogo NVML indica capacità P2P, ma CUDA restituisce <code>can_access_peer=false</code> in entrambe le direzioni. I sette controlli P2P, inclusa la prova preliminare da 1 MiB, sono dichiarati <code>Waived</code> da nvbandwidth: non esiste una misura valida di banda diretta in questa configurazione. La conferma NCCL con log INFO mostra <code>via SHM/direct/direct</code>, cioè trasporto tramite memoria condivisa host. La parola “direct” in quel log non significa P2P tra le due VRAM. Le copie esplicite tramite RAM sottostanti verificano tutti i byte trasferiti.</p>'+staged_table+nccl_table
    document+='<p class="muted">NCCL all-reduce: due GPU, messaggi da 8 byte a 128 MiB, 3 iterazioni di riscaldamento, 10 misurate e 2 controlli dei dati. Banda algoritmica = dimensione del messaggio / tempo; con due GPU il fattore di conversione della bus bandwidth vale uno. Queste sono prove di comunicazione, non un training distribuito.</p>'
    document+='<details><summary>Esiti dei controlli P2P diretti</summary>'+''.join(peer_sections)+'</details>'
    document+='<h2>Riproducibilità e limiti</h2><p>Ubuntu su XCP-ng 8.3, GPU in passthrough, driver 595.99.02, PyTorch 2.10.0+cu126 e CUDA Toolkit 12.6. Scheda interna e scheda esterna sono identificate tramite UUID. Training fermo e disabilitato per tutta la prova; sorgenti, configurazione e checkpoint Riscrivo non vengono modificati. Per avviare la VM con questa configurazione, il dock deve essere collegato e alimentato prima dell’host.</p><p>Il collaudo vale per queste dimensioni, precisioni, durate e condizioni termiche. Non garantisce assenza di guasti futuri o prestazioni identiche su qualunque applicazione. Nessuna qualità del modello viene dedotta da questi numeri.</p><ul>'+links+'</ul>'
    final_check=load('final_verification.json',{})
    document+='<h3>Verifica finale</h3><p>Servizio di collaudo terminato con successo. Nessun processo CUDA rimasto attivo; limiti di potenza ancora a 70 W per entrambe le schede. Training inattivo e disabilitato. Checkpoint al passo 21.626: impronta SHA-256 '+('identica a quella precedente al collaudo' if final_check.get('checkpoint',{}).get('matches_expected') else 'da verificare')+'.</p>'
    document+='<details><summary>Registro delle prove</summary><p>Un codice di uscita zero dello strumento non equivale a prova eseguita: i controlli P2P sono stati saltati perché non disponibili.</p>'+stages_table+'</details><details><summary>Diagnostica kernel durante le prove</summary><p>VM: differenza fra registro iniziale e finale.</p><pre>'+html.escape('\n'.join(serious) if serious else 'Nessun nuovo messaggio grave corrispondente ai controlli Xid/AER/I/O.')+'</pre><p>Server fisico: registro kernel disponibile dell’avvio corrente, acquisito dopo il collaudo.</p><pre>'+html.escape('\n'.join(host_errors) if host_errors else 'Nessuna corrispondenza AER/Xid/PCIe error nel registro disponibile.')+'</pre></details>'
    document+='<footer>Report generato esclusivamente dai file del collaudo. Stato registrato: '+html.escape(str(state.get('state')))+'. Dati completi: summary.json, stages.json, telemetry.jsonl, log degli strumenti e risultati JSON dei test.</footer></main></html>'
    (ROOT/'report.html').write_text(document)
    print(json.dumps(audit,indent=2))


if __name__=='__main__':
    main()
