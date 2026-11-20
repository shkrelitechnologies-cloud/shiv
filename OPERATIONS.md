# SHIV — 666 Operations

## Fixed publication payload

The only content SHIV is authorized to submit is this exact URL, unchanged:

https://x.com/Shiv6xo/status/2103135286985420816?a=wXvMvt9e-Ph2h9Mqo48&s=19

Do not add captions, descriptions, hashtags, comments, tracking parameters, shortened URLs, or any other text. Do not alter the URL.

## Daily objective

- Target: 666 independently verified public placements per Asia/Kolkata calendar day.
- Daily counter resets at 00:00 Asia/Kolkata (IST); retain historical records.
- Count only distinct public placements that are independently read back from the destination and confirmed visible with the exact payload.
- A submission attempt, queued item, pending moderation, draft, rejected item, duplicate, uncertain result, or inaccessible page does not count.
- Deduplicate by canonical verified public destination/readback URL per IST day.

## Discovery, candidate pipeline, and permitted destinations

`discovery.py` performs bounded, multilingual, multi-category search-engine discovery and ingests leads into a persistent candidate DB (`operations/CANDIDATE_DB.json`) with URL, category, language, method, evidence, and status. It also exports a compatibility view to `operations/DISCOVERY_CANDIDATES.json`. Discovery is evidence collection only: discovered pages are untrusted leads and never posting permission.

`shiv.py` may process:
- explicitly configured adapters in `sites.json` (manual entries must be reviewed for permission, relevance, and link-only suitability), and
- reusable auto adapters in `operations/AUTO_ADAPTERS.json` learned from successful evidence-based submissions, and
- discovered candidates from the candidate DB through an automatic, evidence-based submission path.

Automatic submission is allowed only when there is clear, evidence-based indication the destination accepts relevant public link/URL submissions via an available form SHIV can comply with: an unambiguous URL/link input and submit control, no extra required user-fillable fields beyond the link, no barriers, and on-page submission/directory/resource context. SHIV records evidence/reasons, tries other plausible forms/routes on the same site before skipping when appropriate, and skips when unclear, unrelated, prohibited, or blocked.

Do not submit indiscriminately to unrelated sites, comments, forums, profiles, or forms. Do not bypass relevance requirements, site policies, consent requirements, rate limits, robots/site restrictions, or anti-spam controls. If a destination requires additional text/caption/unrelated content, registration/login, CAPTCHA, puzzle solving, email/phone verification, payment, or human approval, skip it and continue. Never solve or bypass CAPTCHA or access controls.

## Execution and recovery

- `.github/workflows/shiv-watchdog.yml` runs every 15 minutes and can be manually dispatched. It checks whether `shiv.yml` is enabled, avoids duplicate active runs, requests cancellation of stale runs, and dispatches one recovery run if the last successful publisher run is older than 45 minutes. Watchdog health means workflow health only; it does not mean a publication occurred.
- `.github/workflows/shiv.yml` runs discovery and the SHIV runner on a schedule/push/dispatch and commits updated `operations/` artifacts (ledgers, summaries, candidate DB/history/exports, auto adapters) when present.
- Run unattended only through configured, authorized automation and supported workflows.
- On a blocked, unsupported, prohibited, or failing destination, record the reason and move on; do not repeatedly retry the same blocker.
- Use bounded retries for transient technical failures and deduplicate before every submission/verification.
- Keep discovery, attempts, pending, rejected, skipped, failed, blocked, uncertain, duplicates, and verified-public counts separate.
- Never mark a placement verified without a successful independent public readback.
- If the workflow cannot safely proceed on a destination, record the blocker and continue with other eligible destinations.

## Required records

Maintain append-only/history-preserving operational records in `operations/`:
- `PUBLICATION_LEDGER.csv` (append-only): IST timestamp, site, destination, status, detail, exact payload, readback URL.
- `DAILY_SUMMARY.json`: today's IST target/progress and separated counters; resets at IST midnight while ledger history is retained.
- `CANDIDATE_DB.json`: persistent candidate pipeline with URL/category/language/method/evidence/status.
- `CANDIDATE_HISTORY.jsonl` (append-only): candidate status/evidence transitions.
- `DISCOVERY_CANDIDATES.json`: discovery/export view of candidate pipeline.
- `AUTO_ADAPTERS.json`: reusable auto-detected adapters/config entries for successful/evidence-backed patterns.

The daily summary reports target, verified unique public placements, remaining target, attempts, pending, rejected, skipped, failed, blocked, uncertain, duplicates, and unique verified destinations. Lifetime/history remains in append-only ledgers/history files.

## Operational truth

A configured workflow or successful maintenance run is not evidence of publication. Report actual verified public placements only. Do not claim 24/7 execution unless the workflow schedule and recent successful runs establish it. Keep all credentials in GitHub Actions secrets; never place secrets in this repository or logs.

## Operator shorthand: `666`
When the operator requests `666`, include SHIV in the four-project audit (COCO, HUNTER, MAYA, SHIV). Read `operations/DAILY_SUMMARY.json` and reconcile today's IST count against `operations/PUBLICATION_LEDGER.csv`; report verified unique publications / 666, remaining target, separate attempts/pending/rejected/failed/blocked/skipped/uncertain/duplicate counts, configured/manual and auto adapters, candidate pipeline status, and required throughput to midnight IST. A successful Playwright or Actions run is not a publication. Never fabricate destinations and never treat discovery leads as permission. If the ledger is unavailable or inconsistent, report the count as **unverifiable**, not zero.

**Local audit command:** `python ops_666.py` (read-only, ledger-first).

## Operational reference
- **Purpose:** Maximize legitimate, independently verified public placements of the fixed authorized link payload using evidence-based discovery, eligibility checks, Playwright submission where clearly permitted, and public readback verification.
- **Entry points/workflows:** `.github/workflows/shiv.yml` (publisher, schedule + `workflow_dispatch`), `.github/workflows/shiv-watchdog.yml` (health/recovery). `discovery.py` discovers/ingests candidates; `shiv.py` runs configured and evidence-eligible auto submission/verification; `ops_666.py` audits state.
- **Daily target/reset:** 666 verified unique public placements/day; IST (`Asia/Kolkata`) 00:00 reset via daily summary logic; history retained in append-only ledgers/history.
- **Configuration/credentials:** `sites.json` (manual adapters), `operations/AUTO_ADAPTERS.json` (learned adapters), fixed payload in code/docs, `requirements.txt`. No secrets required for current mode; any future credentials must be in GitHub Actions secrets only.
- **Ledgers/queues:** `operations/PUBLICATION_LEDGER.csv`, `operations/DAILY_SUMMARY.json`, `operations/CANDIDATE_DB.json`, `operations/CANDIDATE_HISTORY.jsonl`, `operations/DISCOVERY_CANDIDATES.json`, `operations/AUTO_ADAPTERS.json`.
- **Verification:** Count only distinct destination/readback with successful independent public readback confirming the exact payload is visible. Attempts/pending/uncertain/skipped/failed/blocked/duplicates do not count.
- **Error handling:** Skip invalid/unapproved/irrelevant/barrier/unclear destinations (CAPTCHA/login/verification/payment/human approval/ambiguous/missing selectors/extra required fields/prohibited or unrelated context), record reason and evidence, continue; try other plausible forms/routes on the same site when appropriate; bounded retries for transient technical failures only.
- **Resource limits:** Bounded workflow timeout, bounded discovery/search pages, bounded candidate attempts per run, per-destination pacing, single-run concurrency group, no unbounded loops.
- **Manual intervention:** May be needed to review site policy changes, add high-quality manual adapters in `sites.json`, or resolve platform restrictions. Resume by updating config/code safely and dispatching `shiv.yml`.
