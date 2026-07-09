#!/usr/bin/env python3
"""Final comprehensive slug sweep for Bucket-B companies across the non-Workday
ATSes (greenhouse / lever / ashby / smartrecruiters). Standalone manual dev
script (like probe_ats.py) — nothing imports it. Read-only GETs; writes
.github/data/probe_final_results.json as name -> [{board,slug,jobs}, ...].
User instruction: "if the company is not on said list, find the company and get
it on the list ... if the job slug or link is not given find it and add it to companies."
"""
import json, time
from pathlib import Path
import requests

OUT = Path('.github/data/probe_final_results.json')
H = {'User-Agent': 'Mozilla/5.0 (compatible; job-scraper/1.0)'}

TARGETS = {
    # AI-hardware startups
    'Cerebras': ['cerebras', 'cerebrassystems'],
    'Groq': ['groq', 'groqinc', 'groqcareers'],
    'd-Matrix': ['dmatrix', 'dmatrixinc', 'd-matrix'],
    'SiMa.ai': ['sima', 'simaai', 'simatechnologies'],
    'Enfabrica': ['enfabrica', 'enfabricacorporation'],
    'Ayar Labs': ['ayarlabs', 'ayar'],
    'Rivos': ['rivos', 'rivosinc'],
    'Rain AI': ['rain', 'rainai'],
    'Positron': ['positron', 'positronai', 'positronnetworks'],
    'EnCharge AI': ['encharge', 'enchargeai'],
    'Mythic': ['mythic', 'mythicai', 'mythicinc'],
    'TetraMem': ['tetramem'],
    'Hailo': ['hailo', 'hailotech', 'hailoai'],
    'OpenAI': ['openai'],
    'SiFive': ['sifive', 'sifiveinc'],
    'Ampere Computing': ['ampere', 'amperecomputing'],
    'Credo': ['credo', 'credosemiconductor', 'credotechnology'],
    'Alphawave Semi': ['alphawave', 'alphawavesemi', 'alphawaveipgroup'],
    'Silicon Motion': ['siliconmotion', 'siliconmotiontechnology'],
    'Ambiq': ['ambiq', 'ambiqmicro'],
    'pSemi': ['psemi', 'psemicorporation'],
    # Trading / HFT firms with hardware (FPGA) teams
    'Citadel Securities': ['citadelsecurities', 'citadel'],
    'Hudson River Trading': ['hudsonrivertrading', 'wehrt', 'hrt'],
    'Optiver': ['optiver', 'optiverus'],
    'Wolverine Trading': ['wolverinetrading', 'wolverine'],
    'Two Sigma': ['twosigma', 'twosigmainvestments'],
    'Susquehanna (SIG)': ['sig', 'susquehanna', 'sigcareers'],
    'Akuna Capital': ['akunacapital', 'akuna'],
    'Belvedere Trading': ['belvederetrading', 'belvedere'],
}


def gh(s):
    try:
        r = requests.get(f'https://boards-api.greenhouse.io/v1/boards/{s}/jobs', timeout=8, headers=H)
        if r.ok and r.json().get('jobs'):
            return len(r.json()['jobs'])
    except Exception:
        pass
    return None


def lv(s):
    try:
        r = requests.get(f'https://api.lever.co/v0/postings/{s}?mode=json', timeout=8, headers=H)
        if r.ok and isinstance(r.json(), list) and r.json():
            return len(r.json())
    except Exception:
        pass
    return None


def ab(s):
    try:
        r = requests.get(f'https://api.ashbyhq.com/posting-api/job-board/{s}', timeout=8, headers=H)
        if r.ok and r.json().get('jobPostings'):
            return len(r.json()['jobPostings'])
    except Exception:
        pass
    return None


def sr(s):
    try:
        r = requests.get(f'https://api.smartrecruiters.com/v1/companies/{s}/postings', timeout=8, headers=H)
        if r.ok and r.json().get('content'):
            return r.json().get('totalFound', len(r.json()['content']))
    except Exception:
        pass
    return None


BOARDS = [('greenhouse', gh), ('lever', lv), ('ashby', ab), ('smartrecruiters', sr)]


def main():
    results = {}
    for name, slugs in TARGETS.items():
        hits = []
        for s in slugs:
            for board, fn in BOARDS:
                n = fn(s)
                if n is not None:
                    hits.append({'board': board, 'slug': s, 'jobs': n})
                time.sleep(0.1)
        results[name] = hits
        pretty = ', '.join(f"{h['board']}:{h['slug']}({h['jobs']})" for h in hits) or 'NONE'
        print(f'{name:22s} -> {pretty}', flush=True)
    OUT.write_text(json.dumps(results, indent=2))
    print(f"\n{sum(1 for v in results.values() if v)}/{len(TARGETS)} found a standard ATS.")


if __name__ == '__main__':
    main()
