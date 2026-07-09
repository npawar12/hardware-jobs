#!/usr/bin/env python3
"""Probe standard ATS APIs (Greenhouse, Lever, Ashby, Workable, SmartRecruiters)
to auto-discover a company's job-board slug. Workday is NOT probed here (needs
tenant+instance+board dug up manually).

Usage: python .github/scripts/probe_ats.py
Writes results to .github/data/probe_results.json
"""
import json
import re
import sys
import time
from pathlib import Path

import requests

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; job-scraper/1.0)'}
OUT = Path('.github/data/probe_results.json')

# Merged DV + RTL target list. Parenthetical hints kept for slug candidate gen.
COMPANIES = [
    "NVIDIA", "AMD", "Intel", "Qualcomm", "Apple", "Broadcom", "Marvell",
    "Analog Devices (ADI)", "Texas Instruments (TI)", "Google", "Annapurna Labs",
    "Microsoft", "Meta", "Micron", "Samsung Semiconductor", "SK hynix",
    "Kioxia", "NXP", "Microchip", "Infineon", "Renesas", "STMicroelectronics",
    "MediaTek", "Western Digital", "SanDisk", "Silicon Motion", "Ampere Computing",
    "IBM", "Synopsys", "Cadence", "Siemens EDA", "TSMC", "GlobalFoundries",
    "Cisco", "Arista Networks", "Nokia", "Astera Labs", "Credo", "Alphawave Semi",
    "Juniper Networks", "Ciena", "Ambarella", "Synaptics", "Mobileye",
    "Lattice Semiconductor", "Altera", "Achronix", "MaxLinear", "Tesla",
    "Arm", "SiFive", "Rambus", "Ceva", "Cirrus Logic", "Silicon Labs",
    "Skyworks Solutions", "Qorvo", "onsemi", "Monolithic Power Systems",
    "Allegro MicroSystems", "Ambiq", "indie Semiconductor", "MACOM", "pSemi",
    "Keysight", "Teradyne", "Advantest", "Tenstorrent", "Cerebras", "SambaNova",
    "Groq", "Etched", "d-Matrix", "SiMa.ai", "Ventana Micro Systems", "Enfabrica",
    "Lightmatter", "Ayar Labs", "Rivos", "Rain AI", "Positron", "EnCharge AI",
    "Mythic", "TetraMem", "MatX", "Hailo", "OpenAI", "ByteDance", "Waymo", "Zoox",
    "Pure Storage", "Oracle", "Sony", "NetApp", "Dell", "Wolfspeed",
    "Jane Street", "Citadel Securities", "Hudson River Trading", "Jump Trading",
    "Optiver", "IMC Trading", "DRW", "Hyannis Port Research", "Wolverine Trading",
    "Two Sigma", "Tower Research",
]


def candidates(name):
    # strip parenthetical
    base = re.sub(r'\(.*?\)', '', name).strip()
    paren = re.search(r'\((.*?)\)', name)
    alpha = re.sub(r'[^a-z0-9 ]', '', base.lower()).strip()
    words = alpha.split()
    cands = []
    cands.append(''.join(words))            # texasinstruments
    cands.append('-'.join(words))           # texas-instruments
    if len(words) > 1:
        cands.append(words[0])              # texas
    if paren:
        p = re.sub(r'[^a-z0-9]', '', paren.group(1).lower())
        if p:
            cands.insert(0, p)              # adi, ti
    # de-dupe preserving order
    seen = set()
    out = []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def try_greenhouse(slug):
    try:
        r = requests.get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs',
                         timeout=8, headers=HEADERS)
        if r.status_code == 200:
            n = len(r.json().get('jobs', []))
            if n > 0:
                return n
    except Exception:
        pass
    return None


def try_lever(slug):
    try:
        r = requests.get(f'https://api.lever.co/v0/postings/{slug}?mode=json',
                         timeout=8, headers=HEADERS)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                return len(data)
    except Exception:
        pass
    return None


def try_ashby(slug):
    try:
        r = requests.get(f'https://api.ashbyhq.com/posting-api/job-board/{slug}',
                         timeout=8, headers=HEADERS)
        if r.status_code == 200:
            n = len(r.json().get('jobPostings', []))
            if n > 0:
                return n
    except Exception:
        pass
    return None


def try_workable(slug):
    try:
        r = requests.get(f'https://apply.workable.com/api/v1/widget/accounts/{slug}',
                         timeout=8, headers=HEADERS)
        if r.status_code == 200:
            n = len(r.json().get('jobs', []))
            if n > 0:
                return n
    except Exception:
        pass
    return None


def try_smartrecruiters(identifier):
    try:
        r = requests.get(f'https://api.smartrecruiters.com/v1/companies/{identifier}/postings',
                         params={'limit': 10}, timeout=8, headers=HEADERS)
        if r.status_code == 200 and r.json().get('content'):
            return r.json().get('totalFound', 0)
    except Exception:
        pass
    return None


BOARDS = [
    ('greenhouse', try_greenhouse),
    ('lever', try_lever),
    ('ashby', try_ashby),
    ('workable', try_workable),
    ('smartrecruiters', try_smartrecruiters),
]


def main():
    results = {}
    for name in COMPANIES:
        hits = []
        for cand in candidates(name):
            for board, fn in BOARDS:
                n = fn(cand)
                if n is not None:
                    hits.append({'board': board, 'slug': cand, 'jobs': n})
                time.sleep(0.15)
            if hits:  # first candidate that produced any hit wins
                break
        results[name] = hits
        status = ', '.join(f"{h['board']}:{h['slug']}({h['jobs']})" for h in hits) or 'NONE (likely Workday/custom)'
        print(f'{name:32s} -> {status}', flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, 'w') as f:
        json.dump(results, f, indent=2)
    found = sum(1 for v in results.values() if v)
    print(f'\nDone. {found}/{len(COMPANIES)} matched a standard ATS.')


if __name__ == '__main__':
    main()
