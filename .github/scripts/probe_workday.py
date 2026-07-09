#!/usr/bin/env python3
"""Targeted Workday tenant/instance/board discovery for the big semiconductor
companies on the hardware watchlist. Tries curated candidates and verifies each
returns HTTP 200 + a non-empty job list via the CXS POST API. Writes probe_workday_results.json.
"""
import json, time
from pathlib import Path
import requests

OUT = Path('.github/data/probe_workday_results.json')
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; job-scraper/1.0)',
           'Content-Type': 'application/json', 'Accept': 'application/json'}

# name -> list of (tenant, instance, board) candidates to try, best guess first.
CANDIDATES = {
    'Intel':            [('intel', 'wd1', 'External'), ('intel', 'wd1', 'Intel_External_Careers')],
    'AMD':              [('amd', 'wd1', 'External'), ('amd', 'wd1', 'AMD_External')],
    'Broadcom':         [('broadcom', 'wd1', 'External_Career'), ('broadcom', 'wd1', 'External')],
    'Marvell':          [('marvell', 'wd1', 'MarvellCareers2'), ('marvell', 'wd1', 'External')],
    'Analog Devices':   [('analogdevices', 'wd1', 'External'), ('analog', 'wd1', 'External')],
    'Micron':           [('micron', 'wd1', 'External'), ('micron', 'wd5', 'External')],
    'NXP':              [('nxp', 'wd3', 'careers'), ('nxp', 'wd3', 'External')],
    'Renesas':          [('renesas', 'wd3', 'careers'), ('renesas', 'wd1', 'External')],
    'GlobalFoundries':  [('globalfoundries', 'wd1', 'External'), ('gf', 'wd1', 'External')],
    'Ampere Computing': [('amperecomputing', 'wd1', 'Ampere'), ('ampere', 'wd1', 'External')],
    'Arm':              [('arm', 'wd3', 'External'), ('arm', 'wd1', 'External')],
    'Synopsys':         [('synopsys', 'wd1', 'Careers'), ('synopsys', 'wd5', 'External')],
    'Cadence':          [('cadence', 'wd1', 'External_Careers'), ('cadence', 'wd1', 'External')],
    'TSMC':             [('tsmc', 'wd1', 'External'), ('tsmc', 'wd1', 'External')],
    'Nokia':            [('nokia', 'wd3', 'careers'), ('nokia', 'wd3', 'External')],
    'Juniper Networks': [('juniper', 'wd1', 'Juniper'), ('juniper', 'wd5', 'External')],
    'Ciena':            [('ciena', 'wd5', 'careers'), ('ciena', 'wd1', 'External')],
    'Ambarella':        [('ambarella', 'wd1', 'External'), ('ambarella', 'wd5', 'External')],
    'Synaptics':        [('synaptics', 'wd1', 'External'), ('synaptics', 'wd5', 'External')],
    'Mobileye':         [('mobileye', 'wd3', 'careers'), ('mobileye', 'wd1', 'External')],
    'Rambus':           [('rambus', 'wd5', 'External'), ('rambus', 'wd1', 'External')],
    'MaxLinear':        [('maxlinear', 'wd1', 'External'), ('maxlinear', 'wd5', 'External')],
    'Skyworks':         [('skyworks', 'wd1', 'External'), ('skyworkssolutions', 'wd1', 'External')],
    'Qorvo':            [('qorvo', 'wd5', 'External'), ('qorvo', 'wd1', 'External')],
    'onsemi':           [('onsemi', 'wd5', 'careers'), ('onsemi', 'wd1', 'External')],
    'Keysight':         [('keysight', 'wd1', 'External'), ('keysight', 'wd5', 'External')],
    'Teradyne':         [('teradyne', 'wd1', 'External'), ('teradyne', 'wd5', 'External')],
    'Tesla':            [('tesla', 'wd5', 'External'), ('tesla', 'wd1', 'External')],
    'Dell':             [('dell', 'wd1', 'External'), ('dell', 'wd5', 'External')],
    'NetApp':           [('netapp', 'wd1', 'External-NetApp-Careers'), ('netapp', 'wd1', 'External')],
    'Oracle':           [('oracle', 'wd1', 'External'), ('oracle', 'wd5', 'External')],
    'Sony':             [('sony', 'wd1', 'External'), ('sonyelectronics', 'wd1', 'External')],
    'IBM':              [('ibm', 'wd1', 'External'), ('ibm', 'wd5', 'External')],
    'Wolfspeed':        [('wolfspeed', 'wd1', 'External'), ('cree', 'wd1', 'External')],
    'MACOM':            [('macom', 'wd5', 'External'), ('macom', 'wd1', 'External')],
    'Ceva':             [('ceva', 'wd1', 'External'), ('cevadsp', 'wd1', 'External')],
    'SK hynix':         [('skhynix', 'wd3', 'External'), ('skhynix', 'wd1', 'External')],
    'Infineon':         [('infineon', 'wd3', 'External'), ('infineon', 'wd1', 'External')],
    'STMicroelectronics':[('stmicroelectronics', 'wd3', 'External'), ('st', 'wd3', 'External')],
    'MediaTek':         [('mediatek', 'wd3', 'External'), ('mediatek', 'wd1', 'External')],
    'Cirrus Logic':     [('cirrus', 'wd1', 'External'), ('cirruslogic', 'wd1', 'External')],
    'Advantest':        [('advantest', 'wd3', 'External'), ('advantest', 'wd1', 'External')],
}


def probe(tenant, instance, board):
    url = f'https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs'
    try:
        r = requests.post(url, headers=HEADERS,
                          json={'appliedFacets': {}, 'limit': 20, 'offset': 0, 'searchText': ''},
                          timeout=12)
        if r.status_code == 200:
            data = r.json()
            total = data.get('total', 0)
            n = len(data.get('jobPostings', []))
            if n > 0:
                return total, n
    except Exception as e:
        return ('ERR', str(e)[:40])
    return None


def main():
    results = {}
    for name, cands in CANDIDATES.items():
        hit = None
        for (t, i, b) in cands:
            res = probe(t, i, b)
            time.sleep(0.25)
            if res and res[0] != 'ERR':
                hit = {'tenant': t, 'instance': i, 'board': b, 'total': res[0]}
                break
        results[name] = hit
        print(f"{name:22s} -> {hit if hit else 'NONE'}", flush=True)
    OUT.write_text(json.dumps(results, indent=2))
    found = sum(1 for v in results.values() if v)
    print(f'\n{found}/{len(CANDIDATES)} found a working Workday endpoint.')


if __name__ == '__main__':
    main()
