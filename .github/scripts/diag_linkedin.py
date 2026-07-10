#!/usr/bin/env python3
"""Live diagnostic: fetch real LinkedIn hardware postings (with descriptions) and
show, for each Amazon / AMD / Google (and other target) role, the classifier
verdict AND why — so we can eyeball the JD-parsing + senior-rescue on real data.
Standalone; imports hw_classify + scrape_linkedin helpers. Writes nothing.
"""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from hw_classify import (is_relevant_hw, jd_entry_level, _min_years_experience,
                         SENIORITY_REGEX)
from scrape_linkedin import (load_token, run_actor, build_targets, match_company,
                             ROLE_QUERY, default_window)
import yaml

FOCUS = ['AMD', 'Google', 'Amazon']  # highlight these; still report all targets


def title_is_senior(title):
    t = f' {title.lower()} '
    return any(re.search(p, t) for p in SENIORITY_REGEX)


def reason(title, desc):
    my = _min_years_experience(f' {(desc or "").lower()} ')
    jl = jd_entry_level(desc)
    jls = jd_entry_level(desc, strict=True)
    bits = []
    if title_is_senior(title):
        bits.append('SENIOR-title')
        bits.append(f'strictJD={jls}')
    bits.append(f'jd_entry={jl}')
    bits.append(f'minYrs={my}')
    bits.append(f'descLen={len(desc or "")}')
    return ' '.join(bits)


def main():
    token = load_token()
    if not token:
        sys.exit(1)
    cfg = yaml.safe_load(open('linkedin_companies.yml', encoding='utf-8'))
    targets = build_targets(cfg)
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    window = default_window()
    # Only fetch the FOCUS companies (keeps the diagnostic cheap).
    focus_targets = [t for t in targets if t[0].split(' /')[0] in FOCUS or t[0] in FOCUS]
    raw = []
    for _display, search_term, _pats in focus_targets:
        raw.extend(run_actor(token, search_term, ROLE_QUERY, window, count))
    print(f'Fetched {len(raw)} raw US postings.\n')
    shown = 0
    for it in raw:
        title = it.get('title', '')
        comp = match_company(it.get('companyName', ''), targets)
        if not comp:
            continue
        focus = comp.split(' /')[0] in FOCUS or comp in FOCUS
        if not focus:
            continue
        desc = it.get('description', '')
        verdict = 'MATCH' if is_relevant_hw(title, desc) else 'skip '
        print(f'[{verdict}] {comp:22s} | {title}')
        print(f'          {reason(title, desc)} | {it.get("location","")}')
        shown += 1
    if not shown:
        print('(No Amazon/AMD/Google roles in this slice — LinkedIn returns a variable sample; try a higher count.)')


if __name__ == '__main__':
    main()
