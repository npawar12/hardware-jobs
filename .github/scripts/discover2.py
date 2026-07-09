#!/usr/bin/env python3
"""Second-pass ATS slug discovery for companies the first probe missed.
Richer candidates (suffix variants + explicit aliases). Writes probe2_results.json.
"""
import json, re, time
from pathlib import Path
import requests

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; job-scraper/1.0)'}
OUT = Path('.github/data/probe2_results.json')

# companies still missing a standard-ATS slug, with alias hints
TARGETS = {
    'Cerebras': ['cerebras', 'cerebrassystems'],
    'SambaNova': ['sambanova', 'sambanovasystems'],
    'Groq': ['groq', 'groqinc'],
    'Etched': ['etched', 'etchedai'],
    'd-Matrix': ['dmatrix', 'd-matrix', 'dmatrixinc'],
    'SiMa.ai': ['sima', 'simaai', 'sima-ai'],
    'Enfabrica': ['enfabrica'],
    'Ayar Labs': ['ayarlabs', 'ayar'],
    'Rivos': ['rivos', 'rivosinc'],
    'Rain AI': ['rain', 'rainai', 'rainneuromorphics'],
    'Positron': ['positron', 'positronai'],
    'EnCharge AI': ['encharge', 'enchargeai'],
    'Mythic': ['mythic', 'mythicai'],
    'TetraMem': ['tetramem'],
    'Hailo': ['hailo', 'hailotech'],
    'OpenAI': ['openai'],
    'SiFive': ['sifive', 'sifiveinc'],
    'Ampere Computing': ['amperecomputing', 'ampere'],
    'Rambus': ['rambus'],
    'Ceva': ['ceva', 'cevadsp'],
    'Achronix': ['achronix', 'achronixsemiconductor'],
    'MaxLinear': ['maxlinear'],
    'Credo': ['credo', 'credosemiconductor', 'credotechnology'],
    'Alphawave Semi': ['alphawave', 'alphawavesemi'],
    'Ambarella': ['ambarella'],
    'Synaptics': ['synaptics'],
    'Mobileye': ['mobileye'],
    'Silicon Motion': ['siliconmotion'],
    'Ambiq': ['ambiq', 'ambiqmicro'],
    'MACOM': ['macom'],
    'Wolfspeed': ['wolfspeed'],
    'Citadel Securities': ['citadelsecurities'],
    'Hudson River Trading': ['hudsonrivertrading', 'wehrt'],
    'Optiver': ['optiver'],
    'DRW': ['drw', 'drweng', 'drwtrading'],
    'Wolverine Trading': ['wolverinetrading', 'wolverine'],
    'Two Sigma': ['twosigma'],
    'Tower Research': ['towerresearchcapital', 'tower'],
    'Nokia': ['nokia'],
    'Juniper Networks': ['juniper', 'junipernetworks'],
    'Ciena': ['ciena'],
}


def try_greenhouse(s):
    try:
        r = requests.get(f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs', timeout=8, headers=HEADERS)
        if r.ok and r.json().get('jobs'):
            return len(r.json()['jobs'])
    except Exception:
        pass
    return None


def try_lever(s):
    try:
        r = requests.get(f'https://api.lever.co/v0/postings/{s}?mode=json', timeout=8, headers=HEADERS)
        if r.ok and isinstance(r.json(), list) and r.json():
            return len(r.json())
    except Exception:
        pass
    return None


def try_ashby(s):
    try:
        r = requests.get(f'https://api.ashbyhq.com/posting-api/job-board/{s}', timeout=8, headers=HEADERS)
        if r.ok and r.json().get('jobPostings'):
            return len(r.json()['jobPostings'])
    except Exception:
        pass
    return None


BOARDS = [('greenhouse', try_greenhouse), ('lever', try_lever), ('ashby', try_ashby)]


def main():
    results = {}
    for name, cands in TARGETS.items():
        hits = []
        for c in cands:
            for board, fn in BOARDS:
                n = fn(c)
                if n is not None:
                    hits.append({'board': board, 'slug': c, 'jobs': n})
                time.sleep(0.12)
        results[name] = hits
        s = ', '.join(f"{h['board']}:{h['slug']}({h['jobs']})" for h in hits) or 'NONE'
        print(f'{name:24s} -> {s}', flush=True)
    OUT.write_text(json.dumps(results, indent=2))
    print(f'\n{sum(1 for v in results.values() if v)}/{len(TARGETS)} found a standard ATS.')


if __name__ == '__main__':
    main()
