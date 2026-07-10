# How This Job Tracker Works

A plain-English guide to the whole system: what runs, when, what it costs, and
how to run it yourself. (The user-facing job list lives in [`README.md`](README.md);
this file explains the machinery behind it.)

---

## The big picture

There are **two independent tracks**, and they both feed the same `README.md`:

| Track | Source | Cost | Companies | Config |
|-------|--------|------|-----------|--------|
| 🔧 **ATS** | Companies' own public career APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Workday) | **Free** | ~52 | [`hardware_companies.yml`](hardware_companies.yml) |
| 🔗 **LinkedIn** | LinkedIn, via the Apify actor `harvestapi/linkedin-job-search` | ~$0.09/run | ~59 | [`linkedin_companies.yml`](linkedin_companies.yml) |

> A company lives on the ATS track whenever it exposes a working public ATS API
> (free + precise apply links); only companies without one fall back to the paid
> LinkedIn track. As we find more ATS endpoints, companies move from LinkedIn → ATS.

Both tracks run every scraped job title (and, for LinkedIn, the job description)
through the **same classifier** ([`hw_classify.py`](.github/scripts/hw_classify.py)),
so only entry-level DV / RTL / ASIC / SoC / FPGA / physical-design roles make it
into the list. Everything is deduplicated, so a role never appears twice.

---

## Track 1 — ATS (free)

**Script:** [`.github/scripts/scrape_hardware.py`](.github/scripts/scrape_hardware.py)

For each company in `hardware_companies.yml`, it calls that company's public ATS
JSON API directly (no login, no key). Example: Greenhouse is
`https://boards-api.greenhouse.io/v1/boards/<slug>/jobs`, Workday is a POST to
`https://<tenant>.<instance>.myworkdayjobs.com/wday/cxs/<tenant>/<board>/jobs`.

It keeps a job only if the **title** passes the classifier and the location is
US/Canada. Apply links point straight at the company's real posting.

Because this hits public APIs, it costs **nothing** — run it as often as you like.

**Writes:** the `<!-- TABLE_START hardware -->` section of `README.md`,
`hardware_listings.json`, and `.github/data/seen_hardware.json` (the dedup memory).

---

## Track 2 — LinkedIn (Apify)

**Script:** [`.github/scripts/scrape_linkedin.py`](.github/scripts/scrape_linkedin.py)

These are companies that don't expose a scrapeable public ATS (Apple, Google,
Amazon, AMD, the big semis/EDA, AI-silicon startups, trading firms). It reaches
them through LinkedIn using the Apify actor **`harvestapi/linkedin-job-search`**.

It runs **one search per company** so every company gets its own budget. The
exact request sent to Apify:

```python
endpoint = "https://api.apify.com/v2/acts/harvestapi~linkedin-job-search/run-sync-get-dataset-items?token=<APIFY_TOKEN>"
payload = {
    "jobTitles":  [ROLE_QUERY],     # boolean OR of DV/RTL/ASIC/FPGA/... terms
    "company":    ["AMD"],          # one company per call
    "locations":  ["United States"],
    "postedLimit": "24h",           # "24h" daily, "week" on Mondays
    "maxItems":   75,               # cap per company (billed per job returned)
}
```

The returned jobs (with full descriptions) then go through the classifier — which
reads the description to catch entry-level roles whose title doesn't say "new grad"
— plus a company-name re-check and a US-location check.

**Writes:** the `<!-- TABLE_START linkedin -->` section of `README.md`,
`linkedin_listings.json`, and `.github/data/seen_linkedin.json`.

### The 24h vs. week window
- **Daily runs use a 24-hour window** (`postedLimit: "24h"`) — it only fetches
  jobs posted in the last day, so you don't re-pay for the same postings every day.
- **On Mondays it widens to a full week** (`postedLimit: "week"`) as a catch-up
  sweep, so if a daily run ever fails, nothing slips through the cracks.

---

## The classifier (shared filter)

[`hw_classify.py`](.github/scripts/hw_classify.py) decides what's relevant. In short:

- **Must** match a hardware keyword (design verification, RTL, ASIC, SoC, FPGA,
  physical design, DFT, etc.).
- **Must** look entry-level. Seniority is judged on the **title only**
  (staff / principal / manager / lead / director / II–IV are rejected; "Senior"
  is treated leniently). For LinkedIn, it also reads the job description: a role
  passes unless the JD explicitly requires ≥3 years. "Experienced …" titles are
  soft-rejected (only survive on an explicit new-grad phrase in the JD).
- Rejects wrong domains (software, data, mechanical, analog-only, sales, etc.).

You can test it directly: `python .github/scripts/hw_classify.py` runs its self-test.

---

## When does it run?

Automatic schedules:

| Scraper | Schedule (UTC) | Frequency |
|---------|----------------|-----------|
| ATS (hardware) | `15 * * * *` | **Hourly** (at :15) — it's free, so it runs often |
| LinkedIn (Apify) | `0 9 * * *` → 09:00 (≈ 5:00 AM ET) | Once daily |

The ATS scraper runs **hourly** because it only hits free public APIs. The
LinkedIn scraper stays **daily** because each run costs Apify credit. They share
a `readme-updates` concurrency group so they never write the README at the same
time. **Note:** GitHub's scheduler isn't exact — runs are often 5–20 minutes
late, occasionally more.

> ⚠️ **GitHub Actions minutes:** this repo is currently **public**, and public
> repos get **unlimited** free Action-minutes — so hourly runs cost nothing. If you
> ever switch it to **private**, the free tier drops to **2,000 minutes/month**, and
> hourly ATS runs (~2–3 min each) would use ~1,500–2,000 of that — near the limit.
> In that case, drop the ATS schedule to every 2 hours (`15 */2 * * *`) or add paid
> minutes.

### How the workflows push to a protected `main`
`main` is protected (pull-request-required) so nobody can push random changes. The
scrapers still need to commit listing updates, so both workflows authenticate with
your **`GT_TOK`** personal-access-token secret (repo owner → admin bypass) for both
`checkout` and the final `git push`. The push URL uses `${{ github.repository }}`,
so **renaming the repo won't break it**. If you rotate the token, just update the
`GT_TOK` secret — no code change needed.

---

## Running it on demand (the "midday check" button)

Both workflows have a manual trigger, so you don't have to wait for the morning run:

1. Go to the repo on GitHub → **Actions** tab.
2. Pick **"Scrape Hardware Jobs (Personal)"** or **"Scrape LinkedIn Hardware Jobs (Personal)"**.
3. Click **"Run workflow"** → **Run workflow**.

It scrapes, and if anything new turned up it commits the updated README. Run
either one (ATS is free; LinkedIn is ~$0.09). You can also run them locally:

```bash
python .github/scripts/scrape_hardware.py          # ATS, free
python .github/scripts/scrape_linkedin.py          # LinkedIn (needs APIFY_TOKEN)

# handy flags for the LinkedIn scraper:
python .github/scripts/scrape_linkedin.py --dry-run          # fetch + classify, write nothing
python .github/scripts/scrape_linkedin.py --limit 6         # only first 6 companies (cheap test)
python .github/scripts/scrape_linkedin.py --window week     # force the 7-day window
```

---

## Cost & Apify pricing (how the billing works)

**The ATS track is completely free.** It calls companies' own public career APIs
(Greenhouse/Lever/Ashby/SmartRecruiters/Workday) directly — no account, no key, no
per-request charge. Run it as often as you want; the only "cost" is GitHub Actions
minutes (see the schedule note above).

**The LinkedIn track costs money because it uses Apify.** Here's exactly how that bills:

- **Actor:** [`harvestapi/linkedin-job-search`](https://apify.com/harvestapi/linkedin-job-search).
- **Pricing model: pay-per-result — `$1 per 1,000 jobs returned`** (i.e. `$0.001`
  per job). This is a **per-event** price: **no monthly rental**, and harvestapi
  charges **no Apify platform/compute fees on top** — the $1/1k is the *entire* cost.
- **You pay for jobs actually returned, not per search or per run.** A company that
  has no new postings in the window returns 0 jobs and costs $0. The `maxItems: 75`
  cap only bounds a single busy company — since you're billed per job returned, a
  high cap is essentially free (you only pay if that many relevant jobs truly exist).
- **The 24-hour window is the main cost control.** Each daily run only fetches jobs
  posted in the last day (`postedLimit: "24h"`), so you fetch each posting roughly
  once instead of re-paying for the same week's jobs every day. (Running daily
  against a 7-day window would be ~7× the cost — which is why we don't.)

### What it actually costs

| Action | Jobs fetched | Cost |
|--------|--------------|------|
| Any ATS run (manual or scheduled) | — | **$0** |
| One daily LinkedIn run (24h window) | ~90 | **~$0.09** |
| Monday LinkedIn week-sweep (7-day window) | ~250 | ~$0.25 |
| **Whole month, LinkedIn running daily** | ~3,000 | **~$3–4** |

### The free-tier safety net

Apify's **free plan has a hard `$5/month` usage cap** and **no card on file**, so it
**physically cannot overcharge you** — if you ever hit the cap, runs simply fail
until the month resets rather than billing you. At ~$3–4/month the LinkedIn track
sits comfortably under that ceiling. (The ATS track never touches Apify at all.)

---

## The Apify token

The LinkedIn scraper needs an Apify API token. It's read by `load_token()` from
either the `APIFY_TOKEN` environment variable or a local `.env` file — never
hardcoded, never committed (`.env` is gitignored).

**To set up a new token:**
1. Apify Console → **Settings → API & Integrations** → copy your Personal API token.
2. **For local runs:** put `APIFY_TOKEN=apify_api_yourKey` in a `.env` file at the repo root.
3. **For the daily GitHub Action:** repo → **Settings → Secrets and variables →
   Actions → New repository secret** → name `APIFY_TOKEN`, value your key.
4. First time only: the `harvestapi` actor requires a one-time permission approval
   in the Apify Console (you'll get a `full-permission-actor-not-approved` error
   until you approve it). If your new token is on the same Apify account you
   already approved, it just works.

---

## File map

| File | What it is |
|------|-----------|
| `README.md` | The job list (auto-generated tables: Company / Role / Location / Type / Apply / Age). The posting date is stored invisibly in the Age cell, so age auto-updates without a visible Date column. |
| `LISTINGS.md` | Auto-generated compact **Company / Role / Date** index (both tracks). Diff its git history to see when listings come in and drop off. |
| `hardware_companies.yml` | ATS companies + their API slugs/tenants |
| `linkedin_companies.yml` | LinkedIn companies + name aliases |
| `.github/scripts/scrape_hardware.py` | ATS scraper |
| `.github/scripts/scrape_linkedin.py` | LinkedIn/Apify scraper |
| `.github/scripts/hw_classify.py` | The relevance classifier (shared) |
| `.github/scripts/diag_hw.py` / `diag_linkedin.py` | Dev diagnostics |
| `hardware_listings.json` / `linkedin_listings.json` | Structured copies of the listings |
| `.github/data/seen_*.json` | Dedup memory (job IDs already added) |
| `.github/workflows/*.yml` | The daily schedules + manual-run buttons |
