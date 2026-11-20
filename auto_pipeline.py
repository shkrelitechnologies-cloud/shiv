"""Automatic evidence-based candidate evaluation and submission for SHIV."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from candidate_store import load_db, save_db, set_status, upsert_candidate
from common import (
    AUTO_ADAPTERS_FILE, BLOCK_TERMS, CAPTCHA_SELECTORS, PAYLOAD, Result,
    append_candidate_history, append_ledger, canonical_url, domain_of,
    is_public_http, now_utc_iso, read_json, write_json_atomic,
)

ELIGIBILITY_TERMS = re.compile(
    r"(submit|add|suggest|propose|send).{0,40}(link|url|website|site|resource|page|directory)|"
    r"(link|url|website|site|resource).{0,40}(submit|add|suggest|submission)|"
    r"(submit url|submit site|submit website|add url|add site|add website|add link|suggest a link|suggest site|suggest url)|"
    r"(soumettre|envoyer|ajouter).{0,30}(lien|site|url)|"
    r"(enviar|agregar|añadir).{0,30}(enlace|sitio|url)|"
    r"(einreichen|hinzufügen|vorschlagen).{0,30}(link|website|seite|url)|"
    r"(提交|添加|收录).{0,20}(链接|网站|网址|资源)|"
    r"(送信|登録|追加).{0,20}(リンク|サイト|URL)|"
    r"(제출|추가|등록).{0,20}(링크|사이트|URL)|"
    r"(إرسال|أضف|إضافة).{0,20}(رابط|موقع)|"
    r"(जमा|जोड़ें|सबमिट).{0,20}(लिंक|साइट|वेबसाइट)|"
    r"(kirim|tambah).{0,20}(tautan|situs|url)", re.I
)
DIRECTORY_CONTEXT = re.compile(
    r"(directory|directories|resource|resources|listing|catalog|catalogue|links page|"
    r"link exchange|submit your site|submit website|add your website|"
    r"annuaire|directorio|verzeichnis|diretori|каталог|dizin|目录|ディレクトリ|디렉터리|دليل|निर्देशिका)", re.I
)
NEGATIVE_CONTEXT = re.compile(
    r"(comment|reply|post a message|forum post|profile link|bio link|login to continue|"
    r"sign in to submit|register to submit|create account|paid listing|payment|"
    r"write.*description|article body|blog post|press release)", re.I
)
ROUTE_TERMS = re.compile(
    r"submit|add.?url|add.?site|add.?website|add.?link|suggest|suggest.?site|suggest.?link|"
    r"submit.?site|submit.?url|submit.?link|soumettre|agregar|añadir|einreichen|hinzuf|"
    r"提交|登録|送信|제출|등록|إرسال|إضافة|जमा|kirim|gửi|добав", re.I
)

URL_FIELD_HINTS = re.compile(r"url|link|website|site|homepage|web.?address|domain", re.I)


def evidence_eligible_context(ev: dict) -> tuple[bool, str]:
    if ev.get("has_negative_context") and not ev.get("has_directory_context"):
        return False, "negative_or_unrelated_context"
    if ev.get("has_submit_language") or ev.get("has_directory_context"):
        return True, "submission_or_directory_context_detected"
    return False, "insufficient_submission_context"


def detect_barrier_text(text: str) -> str | None:
    if not text:
        return None
    if BLOCK_TERMS.search(text[:20000]):
        return "login_or_verification_barrier"
    return None


def page_barrier(page) -> str | None:
    for selector in CAPTCHA_SELECTORS:
        try:
            if page.locator(selector).count() > 0:
                return "captcha_or_human_verification"
        except Exception:
            pass
    try:
        body = page.locator("body").inner_text(timeout=2500)
        b = detect_barrier_text(body)
        if b:
            return b
    except Exception:
        pass
    return None


def _css_escape_ident(value: str) -> str:
    return re.sub(r"([^\w-])", lambda m: "\\" + m.group(1), value)


def element_selector(el) -> str:
    try:
        info = el.evaluate(
            """e => ({
                id: e.id || '',
                name: e.getAttribute('name') || '',
                type: e.getAttribute('type') || '',
                tag: e.tagName.toLowerCase(),
                formId: e.form && e.form.id || '',
                placeholder: e.getAttribute('placeholder') || ''
            })"""
        )
    except Exception:
        return ""
    tag = info.get("tag") or "input"
    if info.get("id"):
        return f"#{_css_escape_ident(info['id'])}"
    if info.get("name"):
        sel = f'{tag}[name="{info["name"]}"]'
        if info.get("formId"):
            return f'#{_css_escape_ident(info["formId"])} {sel}'
        return sel
    if info.get("placeholder"):
        return f'{tag}[placeholder="{info["placeholder"]}"]'
    if info.get("type"):
        return f'{tag}[type="{info["type"]}"]'
    return tag


def describe_input(el) -> dict:
    try:
        return el.evaluate(
            """e => {
              const labelFor = e.id ? document.querySelector(`label[for="${CSS.escape(e.id)}"]`) : null;
              const wrap = e.closest('label');
              const label = (labelFor?.innerText || wrap?.innerText || '').trim().slice(0,120);
              return {
                tag: e.tagName.toLowerCase(),
                type: (e.getAttribute('type')||'text').toLowerCase(),
                name: e.getAttribute('name')||'',
                id: e.id||'',
                placeholder: e.getAttribute('placeholder')||'',
                required: !!(e.required || e.getAttribute('aria-required')==='true'),
                visible: !!(e.offsetParent || e.getClientRects().length),
                disabled: !!e.disabled,
                readonly: !!e.readOnly,
                value: e.value||'',
                label: label,
              };
            }"""
        )
    except Exception:
        return {}


def is_url_candidate(desc: dict) -> bool:
    typ = (desc.get("type") or "").lower()
    if typ in ("hidden", "submit", "button", "image", "reset", "checkbox", "radio", "file", "password", "email"):
        if typ == "url":
            return True
        return False
    if desc.get("tag") not in ("input", "textarea"):
        return False
    if typ == "url":
        return True
    hay = " ".join([desc.get("name", ""), desc.get("id", ""), desc.get("placeholder", ""), desc.get("label", "")]).lower()
    return bool(URL_FIELD_HINTS.search(hay))


def form_analysis(page, form) -> dict | None:
    try:
        controls = form.locator('input, textarea, select')
        n = controls.count()
    except Exception:
        return None
    descs = []
    for i in range(min(n, 40)):
        el = controls.nth(i)
        d = describe_input(el)
        if d:
            d["selector"] = element_selector(el)
            d["index"] = i
            descs.append(d)
    url_fields = [d for d in descs if d.get("visible") and not d.get("disabled") and not d.get("readonly") and is_url_candidate(d)]
    if len(url_fields) != 1:
        return None
    url_field = url_fields[0]
    # other required visible editable fields beyond link are not allowed
    other_blockers = []
    for d in descs:
        if d is url_field:
            continue
        typ = (d.get("type") or "text").lower()
        tag = d.get("tag")
        if typ in ("hidden", "submit", "button", "image", "reset"):
            continue
        if not d.get("visible") or d.get("disabled") or d.get("readonly"):
            continue
        # checkboxes/radios/selects/textareas/other inputs
        if d.get("required") or typ in ("checkbox", "radio", "file") or tag in ("select", "textarea") or typ in ("email", "password", "tel", "number", "search", "text", "url"):
            # allow prefilled hidden-like? visible means user-facing
            other_blockers.append({k: d.get(k) for k in ("tag", "type", "name", "id", "required", "label", "placeholder")})
    if other_blockers:
        return {"eligible": False, "reason": "extra_required_or_user_fields", "url_field": url_field, "blockers": other_blockers}

    # find submit control inside form
    submits = form.locator('button[type="submit"], input[type="submit"], button:not([type]), input[type="image"]')
    submit_selector = ""
    submit_count = 0
    try:
        submit_count = submits.count()
    except Exception:
        submit_count = 0
    chosen_submit = None
    for i in range(min(submit_count, 10)):
        el = submits.nth(i)
        try:
            if el.is_visible() and el.is_enabled():
                chosen_submit = el
                submit_selector = element_selector(el)
                if not submit_selector:
                    # fallback generic
                    stype = el.evaluate("e=>e.getAttribute('type')||''")
                    if el.evaluate("e=>e.tagName.toLowerCase()") == 'input':
                        submit_selector = f'input[type="{stype or "submit"}"]'
                    else:
                        submit_selector = 'button[type="submit"]'
                break
        except Exception:
            continue
    if chosen_submit is None:
        # some forms use clickable elements; be conservative - skip if no clear submit
        return {"eligible": False, "reason": "submit_control_not_unambiguous", "url_field": url_field}

    return {
        "eligible": True,
        "url_field": url_field,
        "url_selector": url_field.get("selector"),
        "submit_selector": submit_selector,
        "other_fields": len([d for d in descs if d is not url_field]),
    }


def collect_page_evidence(page) -> dict:
    ev = {}
    try:
        ev["title"] = (page.title() or "")[:240]
    except Exception:
        ev["title"] = ""
    try:
        ev["final_url"] = page.url
    except Exception:
        ev["final_url"] = ""
    try:
        body = page.locator("body").inner_text(timeout=2500)[:6000]
    except Exception:
        body = ""
    ev["has_submit_language"] = bool(ELIGIBILITY_TERMS.search((ev.get("title") or "") + "\n" + body))
    ev["has_directory_context"] = bool(DIRECTORY_CONTEXT.search((ev.get("title") or "") + "\n" + body))
    ev["has_negative_context"] = bool(NEGATIVE_CONTEXT.search((ev.get("title") or "") + "\n" + body))
    ev["body_excerpt"] = body[:500]
    return ev


def find_plausible_routes(page, base_url: str, limit: int = 6) -> list[str]:
    base_host = domain_of(base_url)
    found = []
    try:
        links = page.locator("a[href]").evaluate_all(
            "els=>els.map(a=>({href:a.href,text:(a.innerText||a.getAttribute('aria-label')||a.getAttribute('title')||'').trim()}))"
        )
    except Exception:
        return []
    seen = set()
    for item in links:
        href = (item.get("href") or "").strip()
        text = (item.get("text") or "").strip()
        if not href or href.startswith("javascript:") or href.startswith("mailto:"):
            continue
        abs_url = canonical_url(urljoin(base_url, href)) or href
        if not is_public_http(abs_url):
            continue
        if domain_of(abs_url) != base_host:
            continue
        hay = f"{text} {abs_url}"
        if not ROUTE_TERMS.search(hay):
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)
        found.append(abs_url)
        if len(found) >= limit:
            break
    return found


def detect_eligible_forms(page) -> list[dict]:
    forms = []
    try:
        count = page.locator("form").count()
    except Exception:
        count = 0
    for i in range(min(count, 20)):
        form = page.locator("form").nth(i)
        try:
            if not form.is_visible():
                continue
        except Exception:
            pass
        analysis = form_analysis(page, form)
        if analysis and analysis.get("eligible"):
            forms.append(analysis)
    return forms


def verify_payload_visible(page) -> bool:
    try:
        if page.locator(f'a[href="{PAYLOAD}"]').count() > 0:
            return True
    except Exception:
        pass
    try:
        body = page.locator("body").inner_text(timeout=5000)
        return PAYLOAD in body
    except Exception:
        return False


def verify_public_readback(browser, readback_url: str) -> bool:
    if not is_public_http(readback_url):
        return False
    page = browser.new_page()
    try:
        response = page.goto(readback_url, wait_until="domcontentloaded", timeout=20000)
        if response is None or response.status >= 400:
            return False
        if page_barrier(page):
            return False
        return verify_payload_visible(page)
    except Exception:
        return False
    finally:
        page.close()


def build_auto_adapter(site_name: str, page_url: str, form_info: dict, readback_url: str, evidence: dict) -> dict:
    return {
        "name": site_name,
        "url": page_url,
        "readback_url": readback_url,
        "input_selector": form_info.get("url_selector"),
        "submit_selector": form_info.get("submit_selector"),
        "allows_link_only": True,
        "permission_reviewed": False,
        "relevance_reviewed": False,
        "auto_discovered": True,
        "auto_evidence": evidence,
    }


def load_auto_adapters() -> list[dict]:
    data = read_json(AUTO_ADAPTERS_FILE, [])
    if isinstance(data, dict):
        data = data.get("adapters", [])
    if not isinstance(data, list):
        return []
    return [x for x in data if isinstance(x, dict)]


def save_auto_adapters(adapters: list[dict]):
    write_json_atomic(AUTO_ADAPTERS_FILE, {"updated_utc": now_utc_iso(), "adapters": adapters})


def upsert_auto_adapter(adapter: dict):
    adapters = load_auto_adapters()
    key = canonical_url(adapter.get("url", "")) or adapter.get("url")
    out = []
    replaced = False
    for a in adapters:
        if (canonical_url(a.get("url", "")) or a.get("url")) == key and a.get("input_selector") == adapter.get("input_selector"):
            out.append(adapter)
            replaced = True
        else:
            out.append(a)
    if not replaced:
        out.append(adapter)
    # cap file size
    save_auto_adapters(out[-500:])

