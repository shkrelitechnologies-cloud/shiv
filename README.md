# SHIV

SHIV is the fourth 666 operations project. It uses its own Playwright Chromium browser through GitHub Actions.

## Fixed payload

The runner submits only the exact link stored in `OPERATIONS.md`. It never adds captions, hashtags, or other text.

## Run

```bash
python -m pip install -r requirements.txt
python -m playwright install --with-deps chromium
python shiv.py
```

GitHub Actions runs on a 15-minute schedule and can also be started manually.

## Destination registry

`sites.json` starts empty intentionally. Add only manually reviewed destinations whose published rules explicitly permit relevant link-only public submissions. Each entry must provide:

- `name`, `url`
- `permission_reviewed: true`
- `relevance_reviewed: true`
- `allows_link_only: true`
- `input_selector`, `submit_selector`, `readback_url`

The browser is language-independent at the browser-engine level, but forms differ by website and language. SHIV does not guess at arbitrary forms or post the same link indiscriminately across unrelated websites.

CAPTCHA, login/registration, verification, payment, human approval, ambiguous controls, and destinations that require extra text are skipped. No access controls or site policies are bypassed.

## Verification and counters

Only a distinct destination with successful public readback containing the exact payload counts. Attempts, pending, uncertain, skipped, and failed submissions do not count. Daily summaries use Asia/Kolkata dates and reset at midnight IST; the CSV ledger preserves history.

The 666/day goal is a target, not a guarantee. With no approved destinations configured, the workflow safely performs zero submissions.
