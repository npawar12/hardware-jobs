#!/usr/bin/env python3
"""Hardware/ASIC/DV/RTL title classifier for the personal job track.

Precision-first: a title is relevant ONLY if it matches BOTH
  (1) a hardware-domain keyword (DV / RTL / digital / ASIC / SoC / VLSI ...), AND
  (2) an entry-level signal (intern / co-op / new grad / university / associate ...),
and does NOT match a seniority or non-hardware exclusion.

Kept standalone with no I/O so it can be unit-tested directly:
    python .github/scripts/hw_classify.py   # runs the self-test
"""
import re

# (1) Hardware-domain signals. Mostly multi-word to avoid accidental matches.
HW_KEYWORDS = [
    'design verification', 'verification engineer', 'dv engineer', 'hardware verification',
    'formal verification', 'silicon validation', 'post-silicon', 'pre-silicon',
    'rtl', 'rtl design', 'digital design', 'logic design', 'front-end design',
    'asic', 'soc ', 'soc design', 'system-on-chip', 'system on chip',
    'physical design', 'place and route', 'place-and-route', 'synthesis',
    'static timing', 'timing analysis', 'design for test', 'dft ', 'scan insertion',
    'vlsi', 'chip design', 'chip designer', 'ic design', 'ip design',
    'computer architecture', 'microarchitecture', 'micro-architecture',
    'cpu design', 'gpu design', 'processor design', 'core design',
    'systemverilog', 'verilog', 'vhdl', 'uvm', 'emulation engineer',
    'hardware design engineer', 'hardware engineer', 'digital verification',
    'silicon design', 'soc verification', 'design engineer, silicon',
    'fpga', 'fpga design', 'field programmable', 'asic verification',
    'asic design', 'rtl verification', 'design verification engineer',
    'hardware development engineer', 'hardware development', 'digital ic',
    'design engineer - digital', 'design engineer, digital',
    'hardware developer', 'hardware design', 'silicon engineer',
    'soc engineer', 'timing engineer',
]

# (2) Entry-level signals. \bintern\b handled separately via regex.
LEVEL_SUBSTRINGS = [
    'new grad', 'new-grad', 'newgrad', 'entry level', 'entry-level',
    'early career', 'early-career', 'university grad', 'university graduate',
    'college grad', 'campus', 'associate ', 'graduate ', 'rotational',
    'co-op', 'coop', 'co op', 'junior', 'accelerator program',
    'early career program', 'rotation program',
]
LEVEL_REGEX = [r'\bintern\b', r'\binternship\b', r'\buniversity\b', r'\bstudent\b',
               r'\bgraduate\b', r'\bgrad\b', r'\bjr\.?\b', r'\bncg\b']  # NCG = New College Grad

# Seniority / experience exclusions (>~3 yrs). Regex for short tokens.
SENIORITY_REGEX = [
    r'\bsenior\b', r'\bsr\.?\b', r'\bstaff\b', r'\bprincipal\b', r'\bdistinguished\b',
    r'\bfellow\b', r'\blead\b', r'\bmanager\b', r'\bdirector\b', r'\bhead\b',
    r'\bvp\b', r'\bexpert\b', r'\barchitect\b', r'\bii\b', r'\biii\b', r'\biv\b',
    r'\blevel\s*[3-9]\b', r'\bl[3-9]\b', r'\bgrade\s*[3-9]\b',
    r'\bmts\b',  # member of technical staff (usually experienced) unless college/new-grad present
]

# Non-hardware / wrong-domain exclusions.
NON_HW_SIGNALS = [
    'mechanical', 'thermal', 'manufacturing', 'process engineer', 'process integration',
    'chemical', 'materials engineer', 'materials scientist', 'quality engineer',
    'equipment engineer', 'industrial engineer', 'environmental', 'civil engineer',
    'structural', 'sales', 'marketing', 'human resources', 'recruiter',
    'supply chain', 'procurement', 'financial analyst', 'account manager',
    'customer success', 'customer support', 'field application', 'sales engineer',
    'solutions engineer', 'solutions architect', 'legal', 'paralegal', 'accounting',
    'logistics', 'warehouse', 'facilities', 'technician', 'operator', 'assembler',
    'mechanical design', 'packaging engineer', 'test technician', 'reliability engineer',
    'product marketing', 'business development', 'program manager', 'product manager',
    'data scientist', 'data analyst', 'machine learning', 'software development engineer in test',
    # analog kept out per digital/DV-only scope (multi-word to avoid over-rejecting)
    'analog design', 'analog ic', 'analog circuit', 'analog engineer', 'analog/mixed',
]

# Unambiguous hardware phrases used ONLY for the optional description fallback
# (multi-word / high-precision so a stray mention can't create a false match).
STRONG_DESC_HW = [
    'rtl design', 'design verification', 'physical design', 'asic design',
    'soc design', 'systemverilog', 'uvm', 'verilog', 'vhdl', 'digital design',
    'logic design', 'place and route', 'static timing', 'formal verification',
    'design for test', 'pre-silicon', 'post-silicon',
]

# Titles that clearly belong to another discipline — these block the description
# fallback so e.g. a software/data intern whose JD merely mentions RTL can't match.
TITLE_NON_HW_ROLE = [
    'software engineer', 'software developer', 'data engineer', 'data scientist',
    'product manager', 'program manager', 'business', 'sales', 'marketing',
    'mechanical', 'financial', 'research scientist', 'machine learning',
    'frontend', 'front end', 'front-end', 'backend', 'back end', 'back-end',
    'full stack', 'full-stack', 'devops', 'cloud engineer', 'network engineer',
    'security engineer', 'qa engineer', 'sdet', 'web developer', 'ml engineer',
]

# Description-level entry signals (for bare hardware titles with no title marker).
STRONG_ENTRY_PHRASES = [
    'new grad', 'new graduate', 'recent grad', 'recent graduate', 'recently graduated',
    'currently enrolled', 'currently pursuing', 'entry level', 'entry-level',
    'early career', 'early in your career', 'internship', 'co-op', 'university graduate',
    'final year of', 'graduating in', 'pursuing a bachelor', 'pursuing a master',
    'recent college graduate', '0-2 years', '0 to 2 years', '0-1 year',
    'undergraduate', 'undergrad',
]
# Tighter subset used to RESCUE a senior-titled role (AMD etc. occasionally open
# "Senior X" reqs to undergrads / 0-2 yrs). Deliberately excludes boilerplate-prone
# phrases like 'internship'/'co-op'/'early career' and the loose min-years heuristic.
STRICT_ENTRY_PHRASES = [
    'new grad', 'new graduate', 'recent graduate', 'recently graduated',
    'recent college graduate', 'currently enrolled', 'currently pursuing',
    'undergraduate', 'undergrad', 'entry level', 'entry-level',
    '0-2 years', '0 to 2 years', '0-1 year', 'no prior experience',
]
# Years-of-experience extractors — anchored to the word "experience" so that
# incidental phrases like "18 years of age" are ignored. Range patterns capture
# the lower bound.
_YEARS_EXP_RX = [
    re.compile(r'(\d+)\s*\+?\s*years?\s+(?:of\s+)?(?:[a-z][a-z\s,/&.+-]{0,45}?\s+)?experience'),
    re.compile(r'(\d+)\s*(?:-|to|–)\s*\d+\s*years?\s+(?:of\s+)?(?:[a-z][a-z\s,/&.+-]{0,45}?\s+)?experience'),
    re.compile(r'minimum\s+(?:of\s+)?(\d+)\s*\+?\s*years?'),
    re.compile(r'at\s+least\s+(\d+)\s*\+?\s*years?'),
]


def _matches_any_regex(text, patterns):
    return any(re.search(p, text) for p in patterns)


def _min_years_experience(text):
    yrs = []
    for rx in _YEARS_EXP_RX:
        for m in rx.findall(text):
            try:
                yrs.append(int(m))
            except (TypeError, ValueError):
                pass
    return min(yrs) if yrs else None


def jd_entry_level(description, strict=False):
    """Best-effort read of a job description.

    Returns True (entry-level accessible), False (needs experience) or None
    (can't tell). `strict=True` (used to rescue a senior-titled role) requires an
    explicit entry phrase and ignores the loose min-years heuristic, since senior
    JDs often cite a low per-skill year count alongside a high overall bar.
    """
    if not description:
        return None
    d = f' {description.lower()} '
    if strict:
        return True if any(p in d for p in STRICT_ENTRY_PHRASES) else None
    if any(p in d for p in STRONG_ENTRY_PHRASES):
        return True
    my = _min_years_experience(d)
    if my is not None:
        return my <= 2
    return None


def is_relevant_hw(title, description=None):
    """Entry-level hardware/DV/RTL/ASIC roles only.

    Precision-first. Seniority, wrong-domain and entry-level checks are always
    made against the TITLE (so a senior role can't slip in via its JD). The
    optional `description` can only *add* the hardware-domain signal, recovering
    roles whose title carries an entry-level signal but names the discipline only
    in the body (e.g. some rotational "program" roles) — and only when the title
    is not clearly another discipline.
    """
    if not title:
        return False
    t = f' {title.lower()} '

    # Wrong domain -> reject.
    if any(sig in t for sig in NON_HW_SIGNALS):
        return False

    # Seniority split. ONLY "Senior"/"Sr" is treated leniently — AMD etc. open some
    # Senior reqs to undergrads, so a Senior role flows through the same bare-title
    # rule below (passes unless its JD requires >=3 yrs). Everything else senior —
    # staff / principal / manager / director / lead / architect / II-IV / level-3+ /
    # mts — is genuinely senior and hard-rejected. "mts" waived only with college ctx.
    college_ctx = ('college' in t or 'new grad' in t or 'new-grad' in t or 'university' in t)
    for p in SENIORITY_REGEX:
        if p in (r'\bsenior\b', r'\bsr\.?\b'):
            continue
        if p == r'\bmts\b' and college_ctx:
            continue
        if re.search(p, t):
            return False

    title_hw = any(kw in t for kw in HW_KEYWORDS)
    has_level = (any(sig in t for sig in LEVEL_SUBSTRINGS)
                 or _matches_any_regex(t, LEVEL_REGEX))
    other_domain = any(w in t for w in TITLE_NON_HW_ROLE)

    if has_level:
        # Entry-level signal in the title.
        if title_hw:
            return True
        # Hardware named only in the JD (e.g. rotational "program" roles).
        if description and not other_domain:
            d = f' {description.lower()} '
            if any(ph in d for ph in STRONG_DESC_HW):
                return True
        return False

    # No entry-level marker in the title. For a bare hardware title (e.g. plain
    # "ASIC Engineer" / "Design Verification Engineer") with a description, keep it
    # UNLESS the JD explicitly requires experience (>=3 yrs). Silent JDs pass —
    # roles that don't state an experience bar usually don't require one.
    if title_hw and not other_domain and description:
        if jd_entry_level(description) is not False:
            return True
    return False


def infer_type(title):
    """Return a human 'Type' label for the table."""
    t = title.lower()
    if 'co-op' in t or 'coop' in t or 'co op' in t:
        return 'Co-op'
    if re.search(r'\bintern\b|\binternship\b', t):
        for season in ['summer 2027', 'fall 2027', 'spring 2027', 'winter 2027',
                       'summer 2026', 'fall 2026', 'spring 2026']:
            if season in t:
                return season.title() + ' Intern'
        return 'Summer 2027 Intern'
    if any(k in t for k in ['new grad', 'new-grad', 'entry level', 'entry-level',
                            'early career', 'university grad', 'college grad', 'graduate']):
        return 'New Grad'
    return 'New Grad'


# ---- self-test ----
_SHOULD_MATCH = [
    'Design Verification Engineer Intern',
    'RTL Design Engineer - New Grad',
    'ASIC Design Engineer, University Graduate',
    'Digital Design Engineer (Early Career)',
    'Silicon Design Engineer - New College Grad',
    'SoC Design Verification Co-Op',
    'Physical Design Engineer Intern - Summer 2027',
    'Hardware Engineer, DFT - University',
    'Associate RTL Design Engineer',
    'Formal Verification Intern',
]
_SHOULD_NOT_MATCH = [
    'Senior Design Verification Engineer',
    'Staff RTL Design Engineer',
    'Principal ASIC Architect',
    'Software Engineer Intern',
    'Mechanical Engineer - New Grad',
    'Design Verification Engineer',            # no entry-level signal
    'RTL Design Manager',
    'Data Scientist Intern',
    'Process Integration Engineer Intern',
    'Sales Engineer - Semiconductors',
    'Design Verification Engineer III',
    'Product Marketing Intern - Silicon',
    'Field Application Engineer Intern',
]

if __name__ == '__main__':
    ok = True
    for tt in _SHOULD_MATCH:
        r = is_relevant_hw(tt)
        print(f'{"PASS" if r else "FAIL":4s} (want YES) {tt}')
        ok = ok and r
    for tt in _SHOULD_NOT_MATCH:
        r = is_relevant_hw(tt)
        print(f'{"PASS" if not r else "FAIL":4s} (want NO ) {tt}')
        ok = ok and not r
    print('\nALL PASS' if ok else '\nSOME FAILED')
