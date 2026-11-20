#!/usr/bin/env python3
"""SHIV: evidence-based Playwright runner for link-only public destinations.

Processes explicitly configured sites and, when feasible, evidence-eligible
auto-discovered candidates. Only the fixed payload URL may be submitted.
A placement counts only after independent public readback confirms the exact
payload is visible.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from auto_pipeline import (
    build_auto_adapter,
    collect_page_evidence,
    detect_eligible_forms,
    evidence_eligible_context,
    find_plausible_routes,
    load_auto_adapters,
    page_barrier,
    save_auto_adapters,
    upsert_auto_adapter,
    verify_payload_visible,
    verify_public_readback,
)
from candidate_store import load_db, save_db, set_status, upsert_candidate
from common import (
    AUTO_ADAPTERS_FILE,
    LEDGER_FILE,
    PAYLOAD,
    ROOT,
    SITES_FILE,
    SUMMARY_FILE,
    TARGET,
    Result,
    append_ledger,
    canonical_url,
    domain_of,
    is_public_http,
    now_ist,
    now_utc_iso,
    read_json,
    write_json_atomic,
)

AUTO_CANDIDATE_LIMIT = 12
AUTO_ROUTE_LIMIT = 4


def read_ledger_rows_today(today: str) -> list[dict]:
    if not LEDGER_FILE.exists():
        return []
    try:
        with LEDGER_FILE.open(newline="", encoding="utf-8") as f:
            return [r for r in csv.DictReader(f) if (r.get("timestamp_ist") or "").startswith(today)]
    except Exception:
        return []


def load_configured_sites() -> list[dict]:
    data = read_json(SITES_FILE, [])
    if not isinstance(data, list):
        return []
    sites = []
    for site in data:
        if not isinstance(site, dict):
            continue
        if site.get("_instructions"):
            continue
        sites.append(site)
    return sites


def destination_key(site: dict) -> str:
    return canonical_url(site.get("readback_url") or site.get("url") or "") or str(site.get("url") or "")


def eligible_configured(site: dict) -> tuple[bool, str]:
    url = str(site.get("url") or "")
    if not is_public_http(url):
        return False, "invalid_destination_url"
    # Manual configured entries require explicit review flags.
    if site.get("auto_discovered") is True:
        if site.get("allows_link_only") is not True:
            return False, "auto_adapter_not_link_only"
    else:
        if site.get("permission_reviewed") is not True or site.get("allows_link_only") is not True:
            return False, "destination_not_explicitly_approved_for_link_only_posts"
        if site.get("relevance_reviewed") is not True:
            return False, "destination_relevance_not_reviewed"
    if not all(site.get(k) for k in ("input_selector", "submit_selector", "readback_url")):
        return False, "missing_site_specific_selectors_or_readback_url"
    if not is_public_http(str(site.get("readback_url") or "")):
        return False, "invalid_readback_url"
    return True, ""


def verify_public(browser, readback_url: str) -> bool:
    return verify_public_readback(browser, readback_url)


def submit_with_selectors(browser, site: dict, evidence: dict | None = None) -> Result:
    name = str(site.get("name") or domain_of(site.get("url", "")) or "unnamed")
    url = str(site.get("url") or "")
    readback = str(site.get("readback_url") or "")
    page = browser.new_page()
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        if response is None or response.status >= 400:
            return Result(name, url, "failed", f"destination_http_{response.status if response else 'no_response'}", readback, evidence or {})
        barrier = page_barrier(page)
        if barrier:
            return Result(name, url, "skipped", barrier, readback, evidence or {})
        input_sel = site["input_selector"]
        submit_sel = site["submit_selector"]
        if page.locator(input_sel).count() != 1:
            return Result(name, url, "skipped", "link_input_not_unambiguous", readback, evidence or {})
        field = page.locator(input_sel)
        if not field.is_visible() or not field.is_enabled():
            return Result(name, url, "skipped", "link_input_not_available", readback, evidence or {})
        # link-only enforcement: fill only the designated URL input
        try:
            field.fill("")
        except Exception:
            pass
        field.fill(PAYLOAD)
        try:
            if field.input_value() != PAYLOAD:
                return Result(name, url, "failed", "payload_mismatch_before_submit", readback, evidence or {})
        except Exception:
            pass
        submit = page.locator(submit_sel)
        if submit.count() != 1 or not submit.is_visible() or not submit.is_enabled():
            return Result(name, url, "skipped", "submit_control_not_unambiguous", readback, evidence or {})
        submit.click(timeout=10000)
        try:
            page.wait_for_timeout(1500)
        except Exception:
            pass
        barrier = page_barrier(page)
        if barrier:
            return Result(name, url, "skipped", barrier, readback, evidence or {})
        if verify_public(browser, readback):
            return Result(name, url, "verified", "public_readback_contains_exact_payload", readback, evidence or {})
        # if readback differs from current page, also check current page as evidence but only count if public readback URL verifies
        if canonical_url(page.url) != canonical_url(readback) and verify_payload_visible(page):
            # payload visible but not at configured independent readback URL; uncertain to avoid miscount
            return Result(name, url, "uncertain", "payload_visible_but_not_at_configured_readback", readback, evidence or {})
        return Result(name, url, "uncertain", "submission_not_independently_verified", readback, evidence or {})
    except PlaywrightTimeoutError:
        return Result(name, url, "failed", "page_or_action_timeout", readback, evidence or {})
    except Exception as exc:
        return Result(name, url, "failed", f"{type(exc).__name__}: {str(exc)[:180]}", readback, evidence or {})
    finally:
        try:
            page.close()
        except Exception:
            pass



def attempt_form_on_page(browser, page, page_url: str, candidate: dict, form_info: dict, evidence: dict) -> Result | None:
    site_name = candidate.get("title") or domain_of(page_url) or "candidate"
    readback_default = canonical_url(page.url) or page_url
    result_evidence = {
        "candidate_url": candidate.get("url"),
        "page_url": page_url,
        "form": {
            "url_selector": form_info.get("url_selector"),
            "submit_selector": form_info.get("submit_selector"),
        },
        "signals": {k: evidence.get(k) for k in ("title", "has_submit_language", "has_directory_context", "has_negative_context")},
    }
    try:
        url_field = page.locator(form_info["url_selector"])
        if url_field.count() != 1 or not url_field.first.is_visible() or not url_field.first.is_enabled():
            return Result(site_name, page_url, "skipped", "link_input_not_unambiguous", readback_default, result_evidence)
        try:
            url_field.first.fill("")
        except Exception:
            pass
        url_field.first.fill(PAYLOAD)
        try:
            if url_field.first.input_value() != PAYLOAD:
                return Result(site_name, page_url, "failed", "payload_mismatch_before_submit", readback_default, result_evidence)
        except Exception:
            pass
        submit = page.locator(form_info["submit_selector"])
        if submit.count() < 1:
            return Result(site_name, page_url, "skipped", "submit_control_not_unambiguous", readback_default, result_evidence)
        target_submit = None
        for i in range(min(submit.count(), 5)):
            el = submit.nth(i)
            try:
                if el.is_visible() and el.is_enabled():
                    target_submit = el
                    break
            except Exception:
                continue
        if target_submit is None:
            return Result(site_name, page_url, "skipped", "submit_control_not_unambiguous", readback_default, result_evidence)
        target_submit.click(timeout=10000)
        try:
            page.wait_for_timeout(1800)
        except Exception:
            pass
        barrier = page_barrier(page)
        if barrier:
            return Result(site_name, page_url, "skipped", barrier, readback_default, result_evidence)
        current = canonical_url(page.url) or page_url
        if is_public_http(current) and verify_payload_visible(page):
            if verify_public(browser, current):
                adapter = build_auto_adapter(site_name, page_url, form_info, current, result_evidence)
                result_evidence["auto_adapter_saved"] = True
                return Result(site_name, page_url, "verified", "public_readback_contains_exact_payload", current, result_evidence | {"adapter": adapter})
        # payload not publicly verifiable on result page
        return Result(site_name, page_url, "uncertain", "submission_not_independently_verified", current, result_evidence)
    except PlaywrightTimeoutError:
        return Result(site_name, page_url, "failed", "page_or_action_timeout", readback_default, result_evidence)
    except Exception as exc:
        return Result(site_name, page_url, "failed", f"{type(exc).__name__}: {str(exc)[:180]}", readback_default, result_evidence)


def process_candidate(browser, db: dict, candidate: dict, today_verified_destinations: set[str]) -> Result:
    url = candidate.get("url", "")
    name = candidate.get("title") or domain_of(url) or "candidate"
    key = canonical_url(url)
    if not is_public_http(url):
        set_status(db, url, "skipped", "invalid_destination_url", last_result="invalid_destination_url", last_attempt_utc=now_utc_iso())
        return Result(name, url, "skipped", "invalid_destination_url")
    if key in today_verified_destinations:
        set_status(db, url, "duplicate", "already_verified_today", last_result="already_verified_today")
        return Result(name, url, "duplicate", "already_verified_today")

    # Try candidate page and plausible submission routes on same site
    page = browser.new_page()
    tried_routes = []
    try:
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            if response is None or response.status >= 400:
                detail = f"destination_http_{response.status if response else 'no_response'}"
                set_status(db, url, "failed", detail, last_result=detail, last_attempt_utc=now_utc_iso())
                return Result(name, url, "failed", detail)
        except PlaywrightTimeoutError:
            set_status(db, url, "failed", "page_or_action_timeout", last_result="page_or_action_timeout", last_attempt_utc=now_utc_iso())
            return Result(name, url, "failed", "page_or_action_timeout")
        except Exception as exc:
            detail = f"{type(exc).__name__}: {str(exc)[:180]}"
            set_status(db, url, "failed", detail, last_result=detail, last_attempt_utc=now_utc_iso())
            return Result(name, url, "failed", detail)

        barrier = page_barrier(page)
        if barrier:
            set_status(db, url, "skipped", barrier, last_result=barrier, last_attempt_utc=now_utc_iso())
            return Result(name, url, "skipped", barrier)

        routes = [url] + find_plausible_routes(page, url, limit=AUTO_ROUTE_LIMIT)
        # de-dup preserve order
        uniq_routes = []
        seen = set()
        for r in routes:
            cr = canonical_url(r) or r
            if cr in seen:
                continue
            seen.add(cr)
            uniq_routes.append(r)
        routes = uniq_routes[: AUTO_ROUTE_LIMIT + 1]

        any_eligible_form = False
        best_skip_reason = "no_eligible_link_only_form"
        for route in routes:
            tried_routes.append(route)
            try:
                if canonical_url(page.url) != canonical_url(route):
                    resp = page.goto(route, wait_until="domcontentloaded", timeout=20000)
                    if resp is None or resp.status >= 400:
                        best_skip_reason = f"route_http_{resp.status if resp else 'no_response'}"
                        continue
            except Exception:
                continue
            barrier = page_barrier(page)
            if barrier:
                best_skip_reason = barrier
                continue
            ev = collect_page_evidence(page)
            ctx_ok, ctx_reason = evidence_eligible_context(ev)
            forms = detect_eligible_forms(page)
            if forms:
                any_eligible_form = True
                if not ctx_ok and not re.search(r"submit|add|suggest|register-url|suggest-site|add-url", route, re.I):
                    best_skip_reason = ctx_reason
                    continue
            for form_info in forms:
                route_evidence = dict(ev)
                route_evidence["eligibility_reason"] = ctx_reason if ctx_ok else "form_detected_on_submission_route"
                route_evidence["routes_tried"] = tried_routes[:]
                result = attempt_form_on_page(browser, page, route, candidate, form_info, route_evidence)
                if result is None:
                    continue
                if result.status == "verified":
                    adapter = result.evidence.get("adapter") if isinstance(result.evidence, dict) else None
                    if adapter:
                        upsert_auto_adapter(adapter)
                    set_status(db, url, "verified", result.detail,
                               last_result=result.detail, last_attempt_utc=now_utc_iso(),
                               readback_url=result.readback_url, adapter=adapter or {}, method="auto_form")
                    return result
                if result.status == "uncertain":
                    set_status(db, url, "uncertain", result.detail,
                               last_result=result.detail, last_attempt_utc=now_utc_iso(),
                               readback_url=result.readback_url, method="auto_form")
                    return result
                if result.status == "failed":
                    best_skip_reason = result.detail
                    continue
                best_skip_reason = result.detail
        detail = best_skip_reason
        status = "skipped"
        if detail.startswith("destination_http_") or detail.startswith("route_http_"):
            status = "failed"
        set_status(db, url, status, detail, last_result=detail, last_attempt_utc=now_utc_iso(),
                   evidence={"routes_tried": tried_routes[:], "any_eligible_form": any_eligible_form})
        return Result(name, url, status, detail, "", {"routes_tried": tried_routes[:], "any_eligible_form": any_eligible_form})
    finally:
        try:
            page.close()
        except Exception:
            pass


def select_auto_candidates(db: dict, today_verified_destinations: set[str]) -> list[dict]:
    candidates = list((db.get("candidates") or {}).values())

    def score(c):
        status = c.get("status")
        priority = {
            "eligible": 0,
            "discovered": 1,
            "uncertain": 2,
            "failed": 3,
            "skipped": 4,
        }.get(status, 9)
        return (priority, c.get("last_attempt_utc") or "", c.get("first_seen_utc") or "")

    out = []
    for c in sorted(candidates, key=score):
        status = c.get("status")
        url = canonical_url(c.get("url") or "")
        if not url or url in today_verified_destinations:
            continue
        if status in ("verified", "duplicate", "blocked", "ineligible"):
            continue
        reasons = " ".join(c.get("reasons") or []).lower()
        last = (c.get("last_result") or "").lower()
        if status == "skipped" and any(x in (reasons + " " + last) for x in ("captcha", "login", "verification", "barrier", "prohibited", "unrelated", "negative")):
            continue
        if status in ("discovered", "eligible", "uncertain", "failed", "skipped"):
            out.append(c)
        if len(out) >= AUTO_CANDIDATE_LIMIT:
            break
    return out


def write_summary(results: list[Result]):
    today = now_ist().date().isoformat()
    existing = read_json(SUMMARY_FILE, {})
    if not isinstance(existing, dict) or existing.get("date_ist") != today:
        existing = {
            "date_ist": today,
            "target": TARGET,
            "verified_publications": 0,
            "unique_verified_destinations": [],
            "attempts": 0,
            "pending": 0,
            "rejected": 0,
            "skipped": 0,
            "failed": 0,
            "uncertain": 0,
            "duplicates": 0,
            "blocked": 0,
        }

    # preserve historical template-row correction logic (append-only ledger untouched)
    template_rows = 0
    if LEDGER_FILE.exists():
        try:
            with LEDGER_FILE.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    if (
                        (row.get("timestamp_ist") or "").startswith(today)
                        and row.get("site", "") == "unnamed"
                        and not (row.get("destination") or "").strip()
                        and row.get("status") == "skipped"
                        and row.get("detail") == "invalid_destination_url"
                    ):
                        template_rows += 1
        except Exception:
            pass
    previously_excluded = int(existing.get("template_skips_excluded", 0) or 0)
    correction = max(0, template_rows - previously_excluded)
    if correction:
        existing["skipped"] = max(0, int(existing.get("skipped", 0) or 0) - correction)
    existing["template_skips_excluded"] = template_rows

    existing["attempts"] = int(existing.get("attempts", 0) or 0) + sum(1 for r in results if r.status in ("verified", "uncertain", "failed"))
    unique = list(existing.get("unique_verified_destinations") or [])
    for r in results:
        if r.status == "verified":
            dest = canonical_url(r.readback_url or r.destination) or r.destination
            if dest and dest not in unique:
                unique.append(dest)
        elif r.status == "skipped":
            existing["skipped"] = int(existing.get("skipped", 0) or 0) + 1
        elif r.status == "failed":
            existing["failed"] = int(existing.get("failed", 0) or 0) + 1
        elif r.status == "uncertain":
            existing["uncertain"] = int(existing.get("uncertain", 0) or 0) + 1
        elif r.status == "duplicate":
            existing["duplicates"] = int(existing.get("duplicates", 0) or 0) + 1
        elif r.status == "blocked":
            existing["blocked"] = int(existing.get("blocked", 0) or 0) + 1
        elif r.status == "pending":
            existing["pending"] = int(existing.get("pending", 0) or 0) + 1
        elif r.status == "rejected":
            existing["rejected"] = int(existing.get("rejected", 0) or 0) + 1

    existing["unique_verified_destinations"] = unique
    existing["verified_publications"] = len(unique)
    existing["remaining"] = max(0, TARGET - existing["verified_publications"])
    existing["last_run_ist"] = now_ist().isoformat()
    write_json_atomic(SUMMARY_FILE, existing)
    return existing


def main():
    configured_sites = load_configured_sites()
    auto_adapters = load_auto_adapters()
    db = load_db()

    today = now_ist().date().isoformat()
    summary = read_json(SUMMARY_FILE, {})
    today_verified = set()
    if isinstance(summary, dict) and summary.get("date_ist") == today:
        for d in (summary.get("unique_verified_destinations") or []):
            if d:
                today_verified.add(canonical_url(d) or d)

    results: list[Result] = []
    has_db_candidates = bool((db.get("candidates") or {}))
    if configured_sites or auto_adapters or has_db_candidates:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                # 1) configured/manual and learned auto adapters (reusable entries)
                combined = list(configured_sites) + [a for a in auto_adapters if a not in configured_sites]
                seen_adapter_keys = set()
                for site in combined:
                    ok, reason = eligible_configured(site)
                    name = str(site.get("name") or domain_of(site.get("url", "")) or "unnamed")
                    dest = str(site.get("url") or "")
                    readback = str(site.get("readback_url") or "")
                    adapter_key = (canonical_url(dest), site.get("input_selector"), site.get("submit_selector"))
                    if adapter_key in seen_adapter_keys:
                        continue
                    seen_adapter_keys.add(adapter_key)
                    if not ok:
                        if dest:
                            res = Result(name, dest, "skipped", reason, readback)
                            results.append(res)
                            append_ledger(res)
                            print(json.dumps(res.__dict__, ensure_ascii=False))
                        continue
                    vkey = canonical_url(readback or dest) or dest
                    if vkey in today_verified:
                        res = Result(name, dest, "duplicate", "already_verified_today", readback)
                        results.append(res)
                        append_ledger(res)
                        print(json.dumps(res.__dict__, ensure_ascii=False))
                        continue
                    res = submit_with_selectors(browser, site, evidence={"source": "adapter", "auto_discovered": bool(site.get("auto_discovered"))})
                    results.append(res)
                    append_ledger(res)
                    if res.status == "verified":
                        today_verified.add(canonical_url(res.readback_url or res.destination) or res.destination)
                    print(json.dumps(res.__dict__, ensure_ascii=False))
                    time.sleep(2)

                # 2) automatic evidence-based candidate pipeline
                auto_candidates = select_auto_candidates(db, today_verified)
                for cand in auto_candidates:
                    res = process_candidate(browser, db, cand, today_verified)
                    results.append(res)
                    append_ledger(res)
                    if res.status == "verified":
                        today_verified.add(canonical_url(res.readback_url or res.destination) or res.destination)
                    print(json.dumps(res.__dict__, ensure_ascii=False))
                    time.sleep(2)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        save_db(db)
    else:
        print("No configured destinations or discovered candidates; no submission attempt made.")

    summary_out = write_summary(results)
    verified = sum(1 for r in results if r.status == "verified")
    print(f"SHIV run complete: {verified} verified public placements this run; {summary_out.get('verified_publications', 0)}/{TARGET} unique verified today (IST).")


if __name__ == "__main__":
    main()
