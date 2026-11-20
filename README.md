# SHIV

SHIV is the fourth 666 operations project. It uses Playwright Chromium through GitHub Actions to pursue legitimate, independently verified public placements of one fixed link payload.

## Fixed payload

The runner submits only the exact link stored in `OPERATIONS.md` and `common.py`. It never adds captions, hashtags, or other text.

## Run

```bash
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python discovery.py
python shiv.py
python ops_666.py
```

GitHub Actions runs on a schedule and can also be started manually.

## Discovery and submission

- `discovery.py` performs bounded multilingual discovery and maintains a persistent candidate pipeline in `operations/CANDIDATE_DB.json` with URL/category/language/method/evidence/status.
- `shiv.py` processes explicitly configured adapters in `sites.json`, reusable learned adapters in `operations/AUTO_ADAPTERS.json`, and evidence-eligible discovered candidates.
- Automatic submission is attempted only for clear, evidence-based link-only forms: unambiguous URL input + submit, no extra required user-fillable fields beyond the link, no CAPTCHA/login/verification/payment/human-approval barriers, and relevant submission/directory/resource context.
- SHIV records evidence/reasons, tries other plausible forms/routes on the same site before skipping when appropriate, and never bypasses site restrictions.

## Verification and counters

Only a distinct destination/readback with successful independent public readback containing the exact payload counts. Attempts, pending, uncertain, skipped, failed, blocked, and duplicates do not count. Daily summaries use Asia/Kolkata dates and reset at midnight IST; ledgers and candidate history are append-only/preserved.

The 666/day goal is a target, not a guarantee. SHIV reports actual verified placements only.
