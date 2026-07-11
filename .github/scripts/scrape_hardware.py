#!/usr/bin/env python3
"""Personal hardware/ASIC/DV/RTL job scraper.

Fully isolated from the main tech pipeline: its own config
(hardware_companies.yml), its own state (.github/data/seen_hardware.json,
hardware_listings.json) and its own README section (<!-- TABLE_START hardware -->).
It does NOT import or modify scrape_jobs.py / companies.yml / the tech tables.

Usage:
    python .github/scripts/scrape_hardware.py --dry-run   # print matches, write nothing
    python .github/scripts/scrape_hardware.py             # update README + data files
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
import yaml

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo('America/New_York')
except Exception:               # tz database missing -> fall back to naive local time
    _ET = None


def _now_et():
    """Current time in US Eastern, so the 0d/1d age boundary lands on the user's
    midnight (not UTC midnight). Runners are UTC, so age is computed here instead."""
    return datetime.now(_ET) if _ET else datetime.now()

sys.path.insert(0, str(Path(__file__).parent))
from hw_classify import is_relevant_hw, infer_type  # noqa: E402

CONFIG_FILE = Path('hardware_companies.yml')
SEEN_FILE = Path('.github/data/seen_hardware.json')
LISTINGS_FILE = Path('hardware_listings.json')
README_FILE = Path('README.md')
TABLE_MARKER = 'hardware'

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; hw-job-scraper/1.0)'}

# ---------------------------------------------------------------------------
# US / Canada location filter (self-contained copy; mirrors scrape_jobs.py)
# ---------------------------------------------------------------------------
US_SIGNALS = [
    'united states', 'usa', 'u.s.a', ', al', ', ak', ', az', ', ar',
    ', ca', ', co', ', ct', ', de', ', fl', ', ga', ', hi', ', id',
    ', il', ', in', ', ia', ', ks', ', ky', ', la', ', me', ', md',
    ', ma', ', mi', ', mn', ', ms', ', mo', ', mt', ', ne', ', nv',
    ', nh', ', nj', ', nm', ', ny', ', nc', ', nd', ', oh', ', ok',
    ', or', ', pa', ', ri', ', sc', ', sd', ', tn', ', tx', ', ut',
    ', vt', ', va', ', wa', ', wv', ', wi', ', wy', ', dc',
    'new york', 'san francisco', 'los angeles', 'seattle', 'boston',
    'chicago', 'austin', 'denver', 'atlanta', 'miami', 'dallas',
    'raleigh', 'washington d', 'menlo park', 'palo alto', 'mountain view',
    'san jose', 'santa clara', 'redwood city', 'bellevue', 'portland',
    'hillsboro', 'folsom', 'fort collins', 'irvine', 'san diego',
    'phoenix', 'chandler', 'boise', 'durham', 'hopewell',
    'toronto', 'vancouver', 'montreal', 'ottawa', 'calgary', 'canada',
    ', on', ', bc', ', qc', ', ab',
    'us headquarters', 'u.s. headquarters', 'us hq',   # e.g. Ambarella "US Headquarters"
]

NON_US_SIGNALS = [
    'london', 'united kingdom', ', uk', '(uk)', 'u.k.', 'cambridge, gb',
    'berlin', 'munich', 'frankfurt', 'germany', 'dresden',
    'paris', 'france', 'grenoble', 'sophia',
    'amsterdam', 'netherlands', 'eindhoven',
    'dublin', 'ireland',
    'sydney', 'melbourne', 'australia',
    'singapore',
    'bangalore', 'bengaluru', 'hyderabad', 'noida', 'india', 'pune',
    'tokyo', 'japan', 'yokohama',
    'beijing', 'shanghai', 'china', 'shenzhen',
    'taipei', 'hsinchu', 'taiwan',
    'seoul', 'korea',
    'tel aviv', 'israel', 'haifa',
    'mexico city', 'mexico', 'guadalajara',
    'brazil', 'sao paulo',
    'penang', 'malaysia',
    'worldwide', 'global (non-us)',
]


def is_us_location(location):
    if not location or location.strip() == '':
        return False
    loc = location.lower()
    if any(s in loc for s in NON_US_SIGNALS):
        return False
    if loc.strip() in ('remote', 'remote (us)', 'us remote', 'remote - us',
                       'remote, us', 'remote, usa', 'work from home',
                       'remote (canada)', 'canada remote', 'remote, canada'):
        return True
    for s in US_SIGNALS:
        # 2-letter state/province codes ('., ca') must end at a word boundary,
        # else ", mo" matches "rabat, MOrocco" and ", in" matches "..., INdonesia".
        if len(s) == 4 and s.startswith(', '):
            if re.search(re.escape(s) + r'\b', loc):
                return True
        elif s in loc:
            return True
    return False


# ---------------------------------------------------------------------------
# Board scrapers (parameterised on the hardware classifier)
# ---------------------------------------------------------------------------
def _job(company, board, jid, title, location, url):
    return {'id': f'{board}_{jid}', 'company': company, 'title': title,
            'location': location, 'url': url, 'board': board}


def scrape_greenhouse(company, slug):
    url = f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true'
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            print(f'  [{company}] Greenhouse HTTP {r.status_code}')
            return []
        out = []
        for j in r.json().get('jobs', []):
            title = j.get('title', '')
            loc = j.get('location', {}).get('name', '')
            # Greenhouse returns the JD (content=true); strip HTML and let the
            # classifier JD-parse bare titles (e.g. "FPGA Engineer") for experience.
            desc = re.sub(r'<[^>]+>', ' ', j.get('content', '') or '')
            if is_relevant_hw(title, description=desc) and is_us_location(loc):
                out.append(_job(company, f'greenhouse_{slug}', j['id'], title, loc,
                                j.get('absolute_url', '')))
        return out
    except Exception as e:
        print(f'  [{company}] Greenhouse error: {e}')
        return []


def scrape_lever(company, slug):
    url = f'https://api.lever.co/v0/postings/{slug}?mode=json'
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            print(f'  [{company}] Lever HTTP {r.status_code}')
            return []
        out = []
        for j in r.json():
            title = j.get('text', '')
            loc = j.get('categories', {}).get('location', '')
            desc = j.get('descriptionPlain', '') or j.get('description', '')
            if is_relevant_hw(title, description=desc) and is_us_location(loc):
                out.append(_job(company, f'lever_{slug}', j['id'], title, loc,
                                j.get('hostedUrl', '')))
        return out
    except Exception as e:
        print(f'  [{company}] Lever error: {e}')
        return []


def scrape_ashby(company, slug):
    url = f'https://api.ashbyhq.com/posting-api/job-board/{slug}'
    try:
        r = requests.get(url, timeout=10, headers=HEADERS)
        if r.status_code != 200:
            print(f'  [{company}] Ashby HTTP {r.status_code}')
            return []
        out = []
        # Ashby's public posting-api returns {"jobs": [...]} (not "jobPostings"),
        # each with a plain-text description we can JD-parse.
        for j in r.json().get('jobs', []):
            if not j.get('isListed', True):
                continue
            title = j.get('title', '')
            loc = j.get('location', '') or ''
            desc = j.get('descriptionPlain', '') or ''
            if is_relevant_hw(title, description=desc) and is_us_location(loc):
                apply_url = (j.get('jobUrl') or j.get('applyUrl')
                             or f'https://jobs.ashbyhq.com/{slug}/{j.get("id", "")}')
                out.append(_job(company, f'ashby_{slug}', j['id'], title, loc, apply_url))
        return out
    except Exception as e:
        print(f'  [{company}] Ashby error: {e}')
        return []


def scrape_workable(company, slug):
    url = f'https://apply.workable.com/api/v1/widget/accounts/{slug}'
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            print(f'  [{company}] Workable HTTP {r.status_code}')
            return []
        out = []
        for j in r.json().get('jobs', []):
            title = j.get('title', '')
            loc = j.get('location', {})
            country = loc.get('countryCode', '').lower()
            remote = loc.get('remote', False)
            city, region = loc.get('city', ''), loc.get('region', '')
            if not (country in ('us', 'ca') or remote):
                continue
            location = 'Remote' if remote else (f'{city}, {region}' if city and region else city or country.upper())
            if is_relevant_hw(title):
                jid = j.get('shortcode', j.get('id', ''))
                out.append(_job(company, f'workable_{slug}', jid, title, location,
                                f'https://apply.workable.com/{slug}/j/{jid}/'))
        return out
    except Exception as e:
        print(f'  [{company}] Workable error: {e}')
        return []


def scrape_smartrecruiters(company, identifier):
    url = f'https://api.smartrecruiters.com/v1/companies/{identifier}/postings'
    params = {'status': 'PUBLIC', 'limit': 100, 'offset': 0}
    out = []
    while True:
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=10)
            if r.status_code != 200:
                print(f'  [{company}] SmartRecruiters HTTP {r.status_code}')
                break
            data = r.json()
            content = data.get('content', [])
            if not content:
                break
            for j in content:
                title = j.get('name', '')
                loc = j.get('location', {})
                country = loc.get('country', '').lower()
                remote = loc.get('remote', False)
                city, region = loc.get('city', ''), loc.get('region', '')
                if not (country in ('us', 'ca') or remote):
                    continue
                location = 'Remote' if remote else (f'{city}, {region}' if city and region else city or country.upper())
                if is_relevant_hw(title):
                    jid = j.get('id', '')
                    ref = j.get('ref', f'https://jobs.smartrecruiters.com/{identifier}/{jid}')
                    out.append(_job(company, f'smartrecruiters_{identifier}', jid, title, location, ref))
            total = data.get('totalFound', 0)
            params['offset'] += len(content)
            if params['offset'] >= total:
                break
        except Exception as e:
            print(f'  [{company}] SmartRecruiters error: {e}')
            break
    return out


def scrape_workday(company, tenant, instance, board):
    if board:
        api_url = f'https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs'
    else:
        api_url = f'https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/jobs'
    base_url = f'https://{tenant}.{instance}.myworkdayjobs.com'
    # Public job URLs need the site/board segment in the path; the CXS
    # externalPath omits it, so base_url + externalPath 404s. Prepend the board.
    public_base = f'{base_url}/{board}' if board else base_url
    payload = {'appliedFacets': {}, 'limit': 20, 'offset': 0, 'searchText': ''}
    headers = {**HEADERS, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    out, offset = [], 0
    while True:
        payload['offset'] = offset
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=10)
            if r.status_code != 200:
                print(f'  [{company}] Workday HTTP {r.status_code}')
                break
            data = r.json()
            postings = data.get('jobPostings', [])
            if not postings:
                break
            for j in postings:
                title = j.get('title', '')
                loc = j.get('locationsText', '')
                path = j.get('externalPath', '')
                if is_relevant_hw(title) and is_us_location(loc):
                    out.append(_job(company, f'workday_{tenant}', path, title, loc, f'{public_base}{path}'))
            total = data.get('total', 0)
            offset += len(postings)
            if offset >= total:
                break
        except Exception as e:
            print(f'  [{company}] Workday error: {e}')
            break
    return out


SCRAPERS_SLUG = {
    'greenhouse': (scrape_greenhouse, 'slug'),
    'lever': (scrape_lever, 'slug'),
    'ashby': (scrape_ashby, 'slug'),
    'workable': (scrape_workable, 'slug'),
    'smartrecruiters': (scrape_smartrecruiters, 'identifier'),
}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# README table writer (date-desc, then alpha by company; ↳ grouping)
# ---------------------------------------------------------------------------
def _company_sort_key(name):
    name = re.sub(r'[\U0001F000-\U0001FFFF☀-⛿✀-➿]', '', name)
    return name.strip().lower()


def _parse_date(date_str):
    date_str = date_str.strip()
    year = datetime.now().year
    for y in [year, year - 1]:
        try:
            return datetime.strptime(f'{date_str} {y}', '%b %d %Y')
        except ValueError:
            pass
    return None


_DATE_COMMENT_RX = re.compile(r'<!--\s*(.*?)\s*-->')


def _cell_date(cell):
    """Parse a date from a cell whether plain ('Jul 9') or carrying the hidden
    date comment the Age cell uses ('<!--Jul 9-->1d')."""
    m = _DATE_COMMENT_RX.search(cell)
    return _parse_date(m.group(1)) if m else _parse_date(cell.strip())


def _row_date(row):
    for c in reversed([c for c in row.split('|') if c.strip()]):
        d = _cell_date(c)
        if d:
            return d
    return None


def _row_date_str(row):
    for c in reversed([c for c in row.split('|') if c.strip()]):
        m = _DATE_COMMENT_RX.search(c)
        if m and _parse_date(m.group(1)):
            return m.group(1).strip()
        if _parse_date(c.strip()):
            return c.strip()
    return ''


def _age_str(date_obj):
    days = (_now_et().date() - date_obj.date()).days
    return f'{max(days, 0)}d'


def refresh_ages(content):
    """Recompute the visible age in each data row's Age cell from the date hidden
    in that cell's HTML comment ('<!--Jul 9-->1d'), so freshness stays current
    without a visible Date column. Headers/separators/other rows are untouched."""
    out = []
    for line in content.splitlines(keepends=True):
        s = line.rstrip('\n')
        if s.startswith('|') and s.count('|') >= 2:
            parts = s.split('|')
            for i in range(len(parts) - 1, 0, -1):
                m = _DATE_COMMENT_RX.search(parts[i])
                d = _parse_date(m.group(1)) if m else None
                if d:
                    parts[i] = f' <!--{m.group(1)}-->{_age_str(d)} '
                    s = '|'.join(parts)
                    break
            line = s + ('\n' if line.endswith('\n') else '')
        out.append(line)
    return ''.join(out)


def make_row(company, role, location, jtype, url, date, age=None):
    # Date is stashed invisibly in the Age cell (HTML comment) so the table shows
    # only a compact age ('1d') and stays sortable without a Date column.
    if age is None:
        d = _parse_date(date)
        age = _age_str(d) if d else '0d'
    apply_btn = (f'<a href="{url}">'
                 f'<img src="https://i.imgur.com/u1KNU8z.png" width="118" alt="Apply"></a>')
    return f'| {company} | {role} | {location} | {jtype} | {apply_btn} | <!--{date}-->{age} |'


def write_listings_log(content, path='LISTINGS.md'):
    """Regenerate a compact Company | Role | Date index (both tracks) so the git
    history of this file shows when listings come in and drop off over time."""
    lines = ['# Listings Log', '',
             'Auto-generated compact index (Company / Role / Date). Diff this file '
             'over time to see when listings appear and disappear. The live tables '
             'with apply links live in [README.md](README.md).', '']
    for marker, label in [('hardware', 'ATS-sourced'), ('linkedin', 'LinkedIn-sourced')]:
        start = content.find(f'<!-- TABLE_START {marker} -->')
        end = content.find(f'<!-- TABLE_END {marker} -->')
        if start == -1 or end == -1:
            continue
        lines += [f'## {label}', '', '| Company | Role | Date |', '| --- | --- | --- |']
        company = ''
        for row in content[start:end].splitlines():
            if not row.startswith('|'):
                continue
            cols = row.split('|')
            if len(cols) < 4:
                continue
            c1 = cols[1].strip()
            if c1 == 'Company' or not c1 or set(c1) <= set('-: '):
                continue
            if c1 != '↳':
                company = c1
            lines.append(f'| {company} | {cols[2].strip()} | {_row_date_str(row)} |')
        lines.append('')
    Path(path).write_text('\n'.join(lines).rstrip() + '\n', encoding='utf-8')


def insert_row(content, row):
    start = content.find(f'<!-- TABLE_START {TABLE_MARKER} -->')
    end = content.find(f'<!-- TABLE_END {TABLE_MARKER} -->')
    if start == -1 or end == -1:
        print('ERROR: hardware table markers not found in README')
        return None
    sep = re.search(r'\| [-| :]+\|\n', content[start:])
    if not sep:
        print('ERROR: hardware table separator not found')
        return None
    header_end = start + sep.end()
    body = content[header_end:end]
    lines = body.splitlines(keepends=True)

    new_key = _company_sort_key(row.split('|')[1].strip())
    new_date = _row_date(row)
    new_date_str = _row_date_str(row)

    # group continuation rows under same company+date
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def scrape_all(config):
    found = []
    for board, (scraper, field) in SCRAPERS_SLUG.items():
        for entry in config.get(board, []):
            company, slug = entry['name'], entry[field]
            print(f'Checking {company} ({board}/{slug})...')
            found.extend(scraper(company, slug))
            time.sleep(0.4)
    for entry in config.get('workday', []):
        company = entry['name']
        print(f"Checking {company} (workday/{entry['tenant']})...")
        found.extend(scrape_workday(company, entry['tenant'], entry['instance'], entry.get('board', '')))
        time.sleep(0.4)
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='print matches, write nothing')
    args = ap.parse_args()

    if not CONFIG_FILE.exists():
        print(f'ERROR: {CONFIG_FILE} not found')
        sys.exit(1)
    with open(CONFIG_FILE, encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

    seen = load_seen()
    jobs = scrape_all(config)

    new_jobs = [j for j in jobs if j['id'] not in seen]
    print(f'\nMatched {len(jobs)} hardware role(s); {len(new_jobs)} new.')
    for j in new_jobs:
        print(f'  NEW: {j["company"]:24s} | {infer_type(j["title"]):18s} | {j["title"]} @ {j["location"]}')

    if args.dry_run:
        print('\n[dry-run] no files written.')
        return

    with open(README_FILE, encoding='utf-8') as f:
        content = f.read()
    original = content
    listings = load_listings()
    now = _now_et()
    date = now.strftime('%b ') + str(now.day)  # 'Jul 9' (Eastern; portable, no %-d)
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
            'board': j['board'], 'date_added': _now_et().strftime('%Y-%m-%d'),
        })
        seen.add(j['id'])
        added += 1

    # Refresh the Age column on EVERY run (covers both tables), so it stays
    # current even on a run that adds nothing new.
    content = refresh_ages(content)
    if content != original:
        with open(README_FILE, 'w', encoding='utf-8', newline='\n') as f:
            f.write(content)
    write_listings_log(content)   # keep the compact Company|Role|Date log in sync
    if added:
        save_listings(listings)
    save_seen(seen)
    print(f'\nAdded {added} listing(s) to the hardware section; ages refreshed.')


if __name__ == '__main__':
    main()
