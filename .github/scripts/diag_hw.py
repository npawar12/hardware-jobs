#!/usr/bin/env python3
"""Diagnostic: audit hardware classifier precision/recall against live titles.

For every company in hardware_companies.yml, fetch all posting titles and bucket:
  MATCH  -> is_relevant_hw True (would be listed)
  NEAR   -> title contains a hardware keyword but was rejected (why?)
Everything else (no hardware keyword at all) is ignored as clearly irrelevant.

Run: python .github/scripts/diag_hw.py
Writes nothing.
"""
import sys
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from hw_classify import (is_relevant_hw, HW_KEYWORDS, NON_HW_SIGNALS,  # noqa: E402
                         SENIORITY_REGEX, LEVEL_SUBSTRINGS, LEVEL_REGEX,
                         _matches_any_regex)
import re

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; hw-job-scraper/1.0)'}


def reject_reason(title):
    t = f' {title.lower()} '
    for s in NON_HW_SIGNALS:
        if s in t:
            return f'non-hw:{s}'
    for p in SENIORITY_REGEX:
        if re.search(p, t):
            return f'senior:{p}'
    if not any(k in t for k in HW_KEYWORDS):
        return 'no-hw-keyword'
    if not (any(s in t for s in LEVEL_SUBSTRINGS) or _matches_any_regex(t, LEVEL_REGEX)):
        return 'no-entry-level-signal'
    return 'MATCH'


def has_hw_kw(title):
    t = f' {title.lower()} '
    return any(k in t for k in HW_KEYWORDS)


def titles_greenhouse(slug):
    r = requests.get(f'https://boards-api.greenhouse.io/v1/boards/{slug}/jobs', timeout=12, headers=HEADERS)
    return [(j.get('title', ''), j.get('location', {}).get('name', '')) for j in r.json().get('jobs', [])] if r.ok else []


def titles_lever(slug):
    r = requests.get(f'https://api.lever.co/v0/postings/{slug}?mode=json', timeout=12, headers=HEADERS)
    return [(j.get('text', ''), j.get('categories', {}).get('location', '')) for j in r.json()] if r.ok else []


def titles_smartrecruiters(ident):
    out, offset = [], 0
    while True:
        r = requests.get(f'https://api.smartrecruiters.com/v1/companies/{ident}/postings',
                         params={'limit': 100, 'offset': offset}, timeout=12, headers=HEADERS)
        if not r.ok:
            break
        d = r.json()
        c = d.get('content', [])
        if not c:
            break
        out += [(j.get('name', ''), (j.get('location', {}).get('city', '') or '')) for j in c]
        offset += len(c)
        if offset >= d.get('totalFound', 0):
            break
    return out


def main():
    cfg = yaml.safe_load(open('hardware_companies.yml'))
    fetch = {'greenhouse': titles_greenhouse, 'lever': titles_lever,
             'smartrecruiters': titles_smartrecruiters}
    field = {'greenhouse': 'slug', 'lever': 'slug', 'smartrecruiters': 'identifier'}

    total_match, total_near = 0, 0
    for board in ('greenhouse', 'lever', 'smartrecruiters'):
        for e in cfg.get(board, []):
            try:
                titles = fetch[board](e[field[board]])
            except Exception as ex:
                print(f'[{e["name"]}] fetch error: {ex}')
                continue
            matches = [(t, loc) for t, loc in titles if is_relevant_hw(t)]
            nears = [(t, reject_reason(t)) for t, loc in titles
                     if not is_relevant_hw(t) and has_hw_kw(t)]
            if matches or nears:
                print(f'\n=== {e["name"]} ({board}) — {len(titles)} postings ===')
            for t, loc in matches:
                print(f'  MATCH  {t}   [{loc}]')
                total_match += 1
            for t, why in nears:
                print(f'  near   ({why})  {t}')
                total_near += 1
    print(f'\n---\nTOTAL matched: {total_match} | near-misses w/ hw keyword: {total_near}')


if __name__ == '__main__':
    main()
