#!/usr/bin/env python3
"""SHIV: Playwright runner for explicitly approved, link-only public destinations.

This intentionally does not discover arbitrary forms or submit to unrelated sites.
Each destination must be reviewed and explicitly configured in sites.json.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parent
PAYLOAD = "https://x.com/Shiv6xo/status/2103135286985420816?a=wXvMvt9e-Ph2h9Mqo48&s=19"
IST = ZoneInfo("Asia/Kolkata")
TARGET = 666
SITES_FILE = ROOT / "sites.json"
LEDGER_FILE = ROOT / "operations" / "PUBLICATION_LEDGER.csv"
SUMMARY_FILE = ROOT / "operations" / "DAILY_SUMMARY.json"
BLOCK_TERMS = re.compile(
    r"\b(captcha|recaptcha|hcaptcha|verify you are human|security challenge|"
    r"sign in|log in|login required|create an account|email verification|"
    r"phone verification|subscribe to continue)\b", re.I
)
CAPTCHA_SELECTORS = [
    'iframe[src*="captcha"]', 'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]', '[class*="captcha"]',
    '[id*="captcha"]', 'input[name*="captcha"]'
]

@dataclass
class Result:
    site: str
    destination: str
    status: str
    detail: str
    readback_url: str = ""

def now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)

def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def append_result(result: Result):
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LEDGER_FILE.exists()
    with LEDGER_FILE.open("a", encoding="utf-8", newline="") as f:
        if new_file:
            f.write("timestamp_ist,site,destination,status,detail,payload,readback_url\n")
        fields = [now_ist().isoformat(), result.site, result.destination,
                  result.status, result.detail, PAYLOAD, result.readback_url]
        import csv
        csv.writer(f).writerow(fields)

def is_public_http(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.hostname)
    except Exception:
        return False

def detect_barrier(page) -> str | None:
    for selector in CAPTCHA_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return "captcha_or_human_verification"
        except Exception:
            pass
    try:
        body = page.locator("body").inner_text(timeout=2500)[:12000]
        if BLOCK_TERMS.search(body):
            return "login_or_verification_barrier"
    except Exception:
        pass
    return None

def verify_public_readback(browser, readback_url: str) -> bool:
    if not is_public_http(readback_url):
        return False
    page = browser.new_page()
    try:
        response = page.goto(readback_url, wait_until="domcontentloaded", timeout=20000)
        if response is None or response.status >= 400:
            return False
        if detect_barrier(page):
            return False
        return page.locator(f'a[href="{PAYLOAD}"]').count() > 0 or PAYLOAD in page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    finally:
        page.close()

def process_site(browser, site: dict) -> Result:
    name = str(site.get("name", "unnamed"))
    url = str(site.get("url", ""))
    if not is_public_http(url):
        return Result(name, url, "skipped", "invalid_destination_url")
    if site.get("permission_reviewed") is not True or site.get("allows_link_only") is not True:
        return Result(name, url, "skipped", "destination_not_explicitly_approved_for_link_only_posts")
    if site.get("relevance_reviewed") is not True:
        return Result(name, url, "skipped", "destination_relevance_not_reviewed")
    if not all(site.get(k) for k in ("input_selector", "submit_selector", "readback_url")):
        return Result(name, url, "skipped", "missing_site_specific_selectors_or_readback_url")

    page = browser.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if response is None or response.status >= 400:
            return Result(name, url, "failed", f"destination_http_{response.status if response else 'no_response'}")
        barrier = detect_barrier(page)
        if barrier:
            return Result(name, url, "skipped", barrier)
        if page.locator(site["input_selector"]).count() != 1:
            return Result(name, url, "skipped", "link_input_not_unambiguous")
        field = page.locator(site["input_selector"])
        if not field.is_visible() or not field.is_enabled():
            return Result(name, url, "skipped", "link_input_not_available")
        field.fill(PAYLOAD)
        # Enforce link-only payload: do not populate any other fields.
        if field.input_value() != PAYLOAD:
            return Result(name, url, "failed", "payload_mismatch_before_submit")
        submit = page.locator(site["submit_selector"])
        if submit.count() != 1 or not submit.is_visible() or not submit.is_enabled():
            return Result(name, url, "skipped", "submit_control_not_unambiguous")
        submit.click(timeout=10000)
        page.wait_for_timeout(1500)
        barrier = detect_barrier(page)
        if barrier:
            return Result(name, url, "skipped", barrier)
        readback = str(site["readback_url"])
        if verify_public_readback(browser, readback):
            return Result(name, url, "verified", "public_readback_contains_exact_payload", readback)
        return Result(name, url, "uncertain", "submission_not_independently_verified", readback)
    except PlaywrightTimeoutError:
        return Result(name, url, "failed", "page_or_action_timeout")
    except Exception as exc:
        return Result(name, url, "failed", f"{type(exc).__name__}: {str(exc)[:180]}")
    finally:
        page.close()

def write_summary(results: list[Result]):
    date = now_ist().date().isoformat()
    existing = read_json(SUMMARY_FILE, {})
    if existing.get("date_ist") != date:
        existing = {"date_ist": date, "target": TARGET, "verified_publications": 0,
                    "unique_verified_destinations": [], "attempts": 0, "pending": 0,
                    "rejected": 0, "skipped": 0, "failed": 0, "uncertain": 0}
    existing["attempts"] += sum(r.status in ("verified", "uncertain", "failed") for r in results)
    for r in results:
        if r.status == "verified" and r.destination not in existing["unique_verified_destinations"]:
            existing["unique_verified_destinations"].append(r.destination)
        elif r.status == "skipped":
            existing["skipped"] += 1
        elif r.status == "failed":
            existing["failed"] += 1
        elif r.status == "uncertain":
            existing["uncertain"] += 1
    existing["verified_publications"] = len(existing["unique_verified_destinations"])
    existing["remaining"] = max(0, TARGET - existing["verified_publications"])
    existing["last_run_ist"] = now_ist().isoformat()
    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_FILE.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

def main():
    configured_sites = read_json(SITES_FILE, [])
    if not isinstance(configured_sites, list):
        raise SystemExit("sites.json must contain a JSON array")
    # Ignore the human-readable template row; it is not a destination and must
    # never create a fake skipped-attempt event on every scheduled run.
    sites = [
        site for site in configured_sites
        if isinstance(site, dict) and not site.get("_instructions")
    ]
    results: list[Result] = []
    if sites:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for site in sites:
                    result = process_site(browser, site)
                    results.append(result)
                    append_result(result)
                    print(json.dumps(result.__dict__, ensure_ascii=False))
                    time.sleep(2)
            finally:
                browser.close()
    else:
        print("No configured, permission-reviewed destinations; no publication attempt made.")
    write_summary(results)
    verified = sum(r.status == "verified" for r in results)
    print(f"SHIV run complete: {verified} verified public placements; target {TARGET}/IST day.")

if __name__ == "__main__":
    main()
