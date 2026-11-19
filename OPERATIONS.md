# SHIV — 666 Operations

## Fixed publication payload

The only content SHIV is authorized to submit is this exact URL, unchanged:

https://x.com/Shiv6xo/status/2103135286985420816?a=wXvMvt9e-Ph2h9Mqo48&s=19

Do not add captions, descriptions, hashtags, comments, tracking parameters, shortened URLs, or any other text. Do not alter the URL.

## Daily objective

- Target: 666 independently verified public placements per Asia/Kolkata calendar day.
- Daily counter resets at 00:00 Asia/Kolkata (IST); retain historical records.
- Count only distinct public placements that are independently read back from the destination and confirmed visible.
- A submission attempt, queued item, pending moderation, draft, rejected item, duplicate, uncertain result, or inaccessible page does not count.
- Deduplicate by canonical public destination URL per IST day.

## Discovery and permitted destinations

Continuously discover public websites and submission destinations that explicitly permit user-submitted links or link-only posts. Use the exact fixed payload above, and submit only where the destination's purpose and rules make the link appropriate.

Do not submit indiscriminately to unrelated sites, directories, comments, forums, profiles, or forms. Do not bypass relevance requirements, site policies, consent requirements, rate limits, or anti-spam controls. Respect robots directives and published terms. Do not fabricate accounts, identities, engagement, or confirmations.

If a destination requires additional text, a caption, unrelated form content, or a different content type, skip it. If the site requires registration/login, CAPTCHA, puzzle solving, email/phone verification, payment, or human approval to proceed, skip it and continue to the next candidate. Never solve or bypass CAPTCHA or access controls.

## Execution and recovery

- `.github/workflows/shiv-watchdog.yml` runs every 15 minutes and can be manually dispatched. It checks whether `shiv.yml` is enabled, avoids duplicate active runs, requests cancellation of stale runs, and dispatches one recovery run if the last successful publisher run is older than 45 minutes. Watchdog health means workflow health only; it does not mean a publication occurred.

- Run unattended only through configured, authorized automation and supported workflows.
- On a blocked, unsupported, prohibited, or failing destination, record the reason and move on; do not repeatedly retry the same blocker.
- Use bounded retries for transient technical failures and deduplicate before every submission.
- Keep discovery, attempted, submitted, pending, rejected, skipped, failed, and verified-public counts separate.
- Never mark a placement verified without a successful public readback.
- If the workflow cannot safely proceed, record the blocker and continue with other eligible destinations.

## Required records

Maintain a daily summary and append-only publication ledger with at least:
- IST date and timestamp
- destination name and canonical public URL
- exact payload URL
- submission result and moderation state
- public readback URL, timestamp, and verification result
- skip/failure reason where applicable
- deduplication key

The daily summary must report target, verified unique public placements, remaining target, attempts, pending, rejected, skipped, failed, and unique verified destinations. Lifetime totals must remain separate from today's totals.

## Operational truth

A configured workflow or successful maintenance run is not evidence of publication. Report actual verified public placements only. Do not claim 24/7 execution unless the workflow schedule and recent successful runs establish it. Keep all credentials in GitHub Actions secrets; never place secrets in this repository or logs.

## Operator shorthand: `666`
When the operator requests `666`, include SHIV in the four-project audit (COCO, HUNTER, MAYA, SHIV). Read `operations/DAILY_SUMMARY.json` and reconcile today's IST count against `operations/PUBLICATION_LEDGER.csv`; report verified unique publications / 666, remaining target, separate attempts/pending/rejected/failed/skipped/uncertain counts, and required throughput to midnight IST. A successful Playwright or Actions run is not a publication. With no approved destination configured, report zero attempts and zero verified publications; do not fabricate destinations or treat discovery leads as permission. If the ledger is unavailable or inconsistent, report the count as **unverifiable**, not zero.
