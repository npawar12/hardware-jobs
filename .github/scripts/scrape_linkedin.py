#!/usr/bin/env python3
"""LinkedIn-sourced hardware/ASIC/DV/RTL/FPGA job scraper (via Apify).

Covers the companies that DON'T expose a public ATS JSON API (custom/locked
career sites + stealth startups) — the ones scrape_hardware.py can't reach.
Fully isolated: its own config (linkedin_companies.yml), its own state
(.github/data/seen_linkedin.json, linkedin_listings.json) and its own README
section (<!-- TABLE_START linkedin -->). Reuses the SAME classifier + location
filter as scrape_hardware.py so precision is identical (hardware keyword AND
entry-level signal AND US/Canada; seniority + non-hw rejected).

A result is kept only if ALL hold:
  1. its LinkedIn companyName matches one of the allowlisted target companies,
  2. is_relevant_hw(title) is True,
  3. is_us_location(location) is True.

Requires an Apify token in .env (APIFY_TOKEN=...). The token is read locally and
never printed or committed.

Usage:
    python .github/scripts/scrape_linkedin.py --dry-run        # fetch + classify, write nothing
    python .github/scripts/scrape_linkedin.py --count 50       # cap results per search (cost control)
    python .github/scripts/scrape_linkedin.py                  # update README + data files
"""
import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from hw_classify import is_relevant_hw, infer_type          # noqa: E402
from scrape_hardware import (is_us_location, make_row,        # noqa: E402
                             _company_sort_key, _parse_date,
                             _row_date, _row_date_str, refresh_ages,
                             write_listings_log, _now_et)

CONFIG_FILE = Path('linkedin_companies.yml')
SEEN_FILE = Path('.github/data/seen_linkedin.json')
LISTINGS_FILE = Path('linkedin_listings.json')
README_FILE = Path('README.md')
ENV_FILE = Path('.env')
TABLE_MARKER = 'linkedin'

ACTOR = 'harvestapi~linkedin-job-search'
# Boolean OR query covering the in-scope role families (DV / RTL / digital /
# ASIC / FPGA / physical design / hardware engineering / hardware development).
ROLE_QUERY = ('("design verification" OR RTL OR ASIC OR FPGA OR VLSI OR SoC OR '
              '"physical design" OR "hardware engineer" OR "hardware developer" OR '
              '"hardware development" OR "digital design" OR "logic design" OR '
              '"verification engineer" OR "chip design" OR "silicon" OR DFT)')
# One search PER COMPANY (harvestapi `company` facet), so every target company
# gets its own result budget instead of fighting for slots in a shared market
# search. US-only.
SEARCH_LOCATION = 'United States'
# postedLimit windows (harvestapi values). Daily runs use 24h so we don't
# re-fetch (and re-pay for) the same postings every day; a weekly catch-up
# sweep (Mondays) widens to the full week so a skipped/failed daily run can't
# silently drop a role.
WINDOW_DAILY = '24h'
WINDOW_WEEKLY = 'week'


def default_window():
    """24h on most days; full-week catch-up sweep on Mondays (weekday 0)."""
    return WINDOW_WEEKLY if datetime.now().weekday() == 0 else WINDOW_DAILY


def load_token():
    # CI / shell env var first (GitHub Actions secret), then local .env file.
    env_token = os.environ.get('APIFY_TOKEN')
    if env_token:
        return env_token.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line.startswith('APIFY_TOKEN='):
                return line.split('=', 1)[1].strip()
    print('ERROR: APIFY_TOKEN not set (env var or .env).')
    return None


def _normalize(item):
    """Flatten a harvestapi job item (nested company/location/applyMethod) to the
    flat schema the rest of the code expects: title / companyName / location /
    description / url / id."""
    company = item.get('company') or {}
    location = item.get('location') or {}
    apply = item.get('applyMethod') or {}
    return {
        'id': item.get('id', ''),
        'title': item.get('title', ''),
        'companyName': company.get('name', '') if isinstance(company, dict) else str(company),
        'location': location.get('linkedinText', '') if isinstance(location, dict) else str(location),
        'description': item.get('descriptionText', ''),
        'url': (apply.get('companyApplyUrl', '') if isinstance(apply, dict) else '') or item.get('link', ''),
    }


def run_actor(token, company, title, window, limit):
    """Query harvestapi for one company. Returns normalized items (or [])."""
    endpoint = (f'https://api.apify.com/v2/acts/{ACTOR}/'
                f'run-sync-get-dataset-items?token={token}')
    payload = {
        'jobTitles': [title],
        'company': [company],
        'locations': [SEARCH_LOCATION],
        'postedLimit': window,
        'maxItems': limit,
    }
    r = requests.post(endpoint, json=payload, timeout=600)
    if r.status_code not in (200, 201):
        print(f'Apify HTTP {r.status_code}: {r.text[:200]}')
        return []
    data = r.json()
    if not isinstance(data, list):
        return []
    return [_normalize(it) for it in data]


def _clean_search_name(name):
    """valig's companyName facet resolves against LinkedIn's canonical name and
    is picky about the exact string (proper case, no suffixes). Use the display
    name minus any '/'-joined or parenthetical suffix — e.g.
    'Amazon / Annapurna Labs' -> 'Amazon', 'Monolithic Power (MPS)' -> 'Monolithic Power'.
    (Lowercase aliases like 'amd' fail to resolve; 'AMD' works.)
    """
    name = re.split(r'\s*/\s*', name)[0]
    name = re.sub(r'\s*\(.*?\)\s*', ' ', name)
    return name.strip()


def build_targets(config):
    """Return list of (display_name, search_term, [compiled alias regexes]).

    search_term is the cleaned display name passed to valig's companyName facet;
    the alias regexes still re-validate the returned companyName.
    """
    targets = []
    for entry in config.get('companies', []):
        aliases = entry.get('aliases', [])
        pats = [re.compile(r'\b' + re.escape(a.lower()) + r'\b') for a in aliases]
        targets.append((entry['name'], _clean_search_name(entry['name']), pats))
    return targets


def match_company(company_name, targets):
    if not company_name:
        return None
    n = company_name.lower()
    for display, _search, pats in targets:
        if any(p.search(n) for p in pats):
            return display
    return None


# --- README writer (parameterised marker; mirrors scrape_hardware.insert_row) ---
def insert_row(content, row):
    start = content.find(f'<!-- TABLE_START {TABLE_MARKER} -->')
    end = content.find(f'<!-- TABLE_END {TABLE_MARKER} -->')
    if start == -1 or end == -1:
        print('ERROR: linkedin table markers not found in README')
        return None
    sep = re.search(r'\| [-| :]+\|\n', content[start:])
    if not sep:
        print('ERROR: linkedin table separator not found')
        return None
    header_end = start + sep.end()
    body = content[header_end:end]
    lines = body.splitlines(keepends=True)

    new_key = _company_sort_key(row.split('|')[1].strip())
    new_date = _row_date(row)
    new_date_str = _row_date_str(row)

    last_group_idx, in_group = -1, False
    for i, line in enumerate(lines):
        if not line.strip() or not line.startswith('|'):
            continue
        cols = line.split('|')
        if len(cols) < 2:
            continue
        col1 = cols[1].strip()
        if col1 != '↳' and _company_sort_key(col1) == new_key and _row_date_str(line.rstrip()) == new_date_str:
            in_group, last_group_idx = True, i
        elif col1 == '↳' and in_group:
            last_group_idx = i
        elif col1 != '↳':
            in_group = False
    if last_group_idx != -1:
        cont = re.sub(r'^\| [^|]+ \|', '| ↳ |', row, count=1)
        lines.insert(last_group_idx + 1, cont + '\n')
        return content[:header_end] + ''.join(lines) + content[end:]

    insert_at = len(lines)
    for i, line in enumerate(lines):
        if not line.strip() or not line.startswith('|'):
            continue
        cols = line.split('|')
        if len(cols) < 2:
            continue
        col1 = cols[1].strip()
        if col1 == '↳':
            continue
        rd = _row_date(line.rstrip())
        if new_date and rd:
            if new_date > rd:
                insert_at = i
                break
            if new_date == rd and _company_sort_key(col1) > new_key:
                insert_at = i
                break
        elif _company_sort_key(col1) > new_key:
            insert_at = i
            break
    lines.insert(insert_at, row + '\n')
    return content[:header_end] + ''.join(lines) + content[end:]


# --- state ---
def load_seen():
    if SEEN_FILE.exists():
        with open(SEEN_FILE, encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def save_seen(seen):
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SEEN_FILE, 'w', encoding='utf-8') as f:
        json.dump(sorted(seen), f, indent=2)


def load_listings():
    if LISTINGS_FILE.exists():
        with open(LISTINGS_FILE, encoding='utf-8') as f:
            return json.load(f)
    return []


def save_listings(listings):
    with open(LISTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(listings, f, indent=2)


def job_id(item):
    jid = item.get('id') or item.get('url') or item.get('title', '')
    return 'linkedin_' + hashlib.sha1(str(jid).encode()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='fetch + classify, write nothing')
    ap.add_argument('--count', type=int, default=75,
                    help='max results per COMPANY search (maxItems). High so a busy '
                         'company\'s postings are never truncated; you only pay per '
                         'job actually returned, so a high cap is ~free on a 24h window.')
    ap.add_argument('--limit', type=int, default=0, help='only search the first N companies (0 = all; testing/cost control)')
    ap.add_argument('--window', default=None,
                    help='datePosted window (r86400=24h, r604800=7d). Default: 24h, '
                         '7d on Mondays (weekly catch-up sweep).')
    args = ap.parse_args()

    token = load_token()
    if not token:
        sys.exit(1)
    if not CONFIG_FILE.exists():
        print(f'ERROR: {CONFIG_FILE} not found')
        sys.exit(1)
    with open(CONFIG_FILE, encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}
    targets = build_targets(config)
    if args.limit > 0:
        targets = targets[:args.limit]
    window = args.window or default_window()
    print(f'{len(targets)} target companies; querying LinkedIn via harvestapi '
          f'(one search per company, count={args.count} each, window={window}, '
          f'location={SEARCH_LOCATION})...')

    raw = []
    for display, search_term, _pats in targets:
        batch = run_actor(token, search_term, ROLE_QUERY, window, args.count)
        print(f'  {display:24s} -> {len(batch)} raw')
        raw.extend(batch)
    print(f'Fetched {len(raw)} raw postings across {len(targets)} company searches.')

    seen_titles = set()
    matched = []
    for it in raw:
        title = it.get('title', '')
        company_raw = it.get('companyName', '')
        location = it.get('location', '')
        target = match_company(company_raw, targets)
        if not target:
            continue
        if not is_relevant_hw(title, description=it.get('description', '')):
            continue
        if not is_us_location(location):
            continue
        dkey = (target, title.lower().strip(), location.lower().strip())
        if dkey in seen_titles:
            continue
        seen_titles.add(dkey)
        matched.append({
            'id': job_id(it),
            'company': target,
            'title': title,
            'location': location,
            'url': it.get('url', ''),
        })

    seen = load_seen()
    new_jobs = [j for j in matched if j['id'] not in seen]
    print(f'\nMatched {len(matched)} relevant hardware role(s); {len(new_jobs)} new.')
    for j in matched:
        flag = 'NEW ' if j['id'] not in seen else '    '
        print(f'  {flag}{j["company"]:24s} | {infer_type(j["title"]):18s} | {j["title"]} @ {j["location"]}')

    if args.dry_run:
        print('\n[dry-run] no files written.')
        return

    with open(README_FILE, encoding='utf-8') as f:
        content = f.read()
    original = content
    listings = load_listings()
    now = _now_et()
    date = now.strftime('%b ') + str(now.day)  # Eastern, so 0d/1d matches your day
    added = 0
    for j in new_jobs:
        row = make_row(j['company'], j['title'], j['location'], infer_type(j['title']), j['url'], date)
        nc = insert_row(content, row)
        if nc is None:
            continue
        content = nc
        listings.append({
            'company': j['company'], 'role': j['title'], 'location': j['location'],
            'type': infer_type(j['title']), 'url': j['url'],
            'board': 'linkedin', 'date_added': now.strftime('%Y-%m-%d'),
        })
        seen.add(j['id'])
        added += 1

    # Keep the Age column current every run (covers both tables).
    content = refresh_ages(content)
    if content != original:
        with open(README_FILE, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    write_listings_log(content)   # keep the compact Company|Role|Date log in sync
    if added:
        save_listings(listings)
    save_seen(seen)
    print(f'\nAdded {added} listing(s) to the LinkedIn section; ages refreshed.')


if __name__ == '__main__':
    main()
