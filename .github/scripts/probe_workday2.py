#!/usr/bin/env python3
"""Second-pass Workday discovery: board-name matrix for the semis my first
targeted probe missed. Standalone manual dev script (like probe_workday.py) —
nothing imports it. Read-only POSTs to the Workday CXS API; writes
.github/data/probe_workday2_results.json as name -> {tenant,instance,board,total}|null.
User instruction: "if the company is not on said list, find the company and get it
on the list ... if the job slug or link is not given find it and add it to companies."
"""
import json, time
from pathlib import Path
import requests

OUT = Path('.github/data/probe_workday2_results.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; job-scraper/1.0)',
           'Content-Type': 'application/json', 'Accept': 'application/json'}

# tenant guesses per company (still missing a working endpoint).
TENANTS = {
    'AMD': ['amd'],
    'Synopsys': ['synopsys'],
    'Renesas': ['renesas'],
    'Ambarella': ['ambarella'],
    'Synaptics': ['synaptics'],
    'Skyworks': ['skyworks', 'skyworkssolutions'],
    'Qorvo': ['qorvo'],
    'onsemi': ['onsemi'],
    'Keysight': ['keysight'],
    'Teradyne': ['teradyne'],
    'Rambus': ['rambus'],
    'MaxLinear': ['maxlinear'],
    'MACOM': ['macom'],
    'Ceva': ['ceva'],
    'Infineon': ['infineon'],
    'STMicroelectronics': ['stmicroelectronics', 'st'],
    'MediaTek': ['mediatek'],
    'Cirrus Logic': ['cirrus', 'cirruslogic'],
    'Advantest': ['advantest'],
    'Mobileye': ['mobileye'],
    'Arm': ['arm'],
    'Ampere Computing': ['ampere', 'amperecomputing'],
    'NetApp': ['netapp'],
    'Teledyne': ['teledyne'],
    'Lam Research': ['lamresearch', 'lam'],
    'KLA': ['kla', 'klacorp'],
    'Applied Materials': ['appliedmaterials', 'amat'],
}
INSTANCES = ['wd1', 'wd3', 'wd5']
BOARDS = ['External', 'External_Career', 'External_Careers', 'Careers', 'careers',
          'External_Experienced', 'ExternalCareers', 'External_Site', 'jobs']


def probe(tenant, instance, board):
    url = f'https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs'
    try:
        r = requests.post(url, headers=HEADERS,
                          json={'appliedFacets': {}, 'limit': 5, 'offset': 0, 'searchText': ''},
                          timeout=8)
        if r.status_code == 200:
            d = r.json()
            if len(d.get('jobPostings', [])) > 0:
                return d.get('total', 0)
    except Exception:
        pass
    return None


def main():
    results = {}
    for name, tenants in TENANTS.items():
        hit = None
        for t in tenants:
            for i in INSTANCES:
                for b in BOARDS:
                    total = probe(t, i, b)
                    time.sleep(0.08)
                    if total:
                        hit = {'tenant': t, 'instance': i, 'board': b, 'total': total}
                        break
                if hit:
                    break
            if hit:
                break
        results[name] = hit
        print(f"{name:22s} -> {hit if hit else 'NONE'}", flush=True)
    OUT.write_text(json.dumps(results, indent=2))
    print(f"\n{sum(1 for v in results.values() if v)}/{len(TENANTS)} found.")


if __name__ == '__main__':
    main()
