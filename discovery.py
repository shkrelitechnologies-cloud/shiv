#!/usr/bin/env python3
"""SHIV global multilingual destination research and candidate ingestion.

Research/discovery only: discovered pages are untrusted leads and not posting
permission. Evidence is recorded for later eligibility checks before any
submission attempt.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

from candidate_store import export_discovery_view, load_db, save_db, upsert_candidate
from common import canonical_url

ROOT = Path(__file__).resolve().parent

ENGINES = {
    "duckduckgo": "https://html.duckduckgo.com/html/?q={q}",
    "bing": "https://www.bing.com/search?q={q}",
    "mojeek": "https://www.mojeek.com/search?q={q}",
    "yahoo": "https://search.yahoo.com/search?p={q}",
    "brave": "https://search.brave.com/search?q={q}",
    "ecosia": "https://www.ecosia.org/search?q={q}",
    "qwant": "https://www.qwant.com/?q={q}&t=web",
}

# (category, language, query)
QUERY_SPECS = [
    ("directory", "en", "public web directory submit URL add your site link only"),
    ("directory", "en", "open directory suggest a site submit website link form"),
    ("directory", "en", "free website directory add URL submission guidelines"),
    ("resources", "en", "community resources page submit a link add resource URL"),
    ("resources", "en", "public resource list suggest a link submission form"),
    ("startup", "en", "startup directory submit your startup website URL form"),
    ("tools", "en", "tools directory submit a tool website link form"),
    ("local", "en", "business directory add website URL listing submission"),
    ("directory", "es", "directorio web enviar enlace agregar sitio URL reglas"),
    ("directory", "fr", "annuaire web soumettre un lien ajouter site URL règles"),
    ("directory", "de", "Webverzeichnis Website einreichen Link hinzufügen Regeln"),
    ("directory", "pt", "diretório web enviar link adicionar site URL regras"),
    ("directory", "it", "directory web invia link aggiungi sito URL regole"),
    ("directory", "nl", "webdirectory link indienen website toevoegen regels"),
    ("directory", "pl", "katalog stron dodaj link zgłoś stronę zasady"),
    ("directory", "ru", "каталог сайтов добавить ссылку отправить сайт правила"),
    ("directory", "uk", "каталог сайтів додати посилання надіслати сайт правила"),
    ("directory", "tr", "web dizini site ekle bağlantı gönder kurallar"),
    ("directory", "ar", "دليل مواقع إرسال رابط إضافة موقع قواعد"),
    ("directory", "hi", "वेब निर्देशिका लिंक जमा करें वेबसाइट जोड़ें नियम"),
    ("directory", "bn", "ওয়েব ডিরেক্টরি লিঙ্ক জমা দিন ওয়েবসাইট যোগ করুন নিয়ম"),
    ("directory", "id", "direktori web kirim tautan tambah situs aturan"),
    ("directory", "ms", "direktori web hantar pautan tambah laman peraturan"),
    ("directory", "vi", "thư mục web gửi liên kết thêm trang web quy định"),
    ("directory", "th", "ไดเรกทอรีเว็บ ส่งลิงก์ เพิ่มเว็บไซต์ กติกา"),
    ("directory", "ja", "ウェブディレクトリ サイト登録 URL送信 ルール"),
    ("directory", "ko", "웹 디렉터리 사이트 등록 링크 제출 규칙"),
    ("directory", "zh", "网站目录 提交链接 添加网站 规则"),
    ("directory", "zh-hant", "網站目錄 提交連結 新增網站 規則"),
    ("resources", "es", "página de recursos enviar enlace agregar recurso"),
    ("resources", "fr", "page de ressources soumettre un lien ajouter ressource"),
    ("resources", "de", "Ressourcenseite Link vorschlagen Ressource hinzufügen"),
    ("resources", "pt", "página de recursos enviar link adicionar recurso"),
    ("resources", "ja", "リソースページ リンク投稿 リソース追加"),
    ("resources", "ko", "리소스 페이지 링크 제출 자료 추가"),
    ("resources", "zh", "资源页面 提交链接 添加资源"),
    ("directory", "sv", "webbkatalog skicka länk lägg till webbplats regler"),
    ("directory", "no", "nettkatalog send lenke legg til nettsted regler"),
    ("directory", "da", "webkatalog indsende link tilføj hjemmeside regler"),
    ("directory", "fi", "verkkohakemisto lähetä linkki lisää sivusto säännöt"),
    ("directory", "cs", "webový katalog odeslat odkaz přidat web pravidla"),
    ("directory", "ro", "director web trimite link adaugă site reguli"),
    ("directory", "el", "κατάλογος ιστού υποβολή συνδέσμου προσθήκη ιστοσελίδας κανόνες"),
    ("directory", "he", "ספריית אתרים שליחת קישור הוספת אתר כללים"),
]

BLOCK = ("captcha", "verify you are human", "unusual traffic", "access denied",
         "security check", "robot check", "sign in to continue", "forbidden")
TERMS = (
    "submit", "add link", "add url", "add website", "add site", "suggest", "directory",
    "resource", "listing", "submit url", "submit website", "submit link",
    "soumettre", "enlace", "agregar", "directorio", "verzeichnis", "einreichen",
    "リンク", "登録", "링크", "제출", "提交", "收录", "添加", "رابط", "إضافة", "دليل",
    "वेबसाइट", "लिंक", "निर्देशिका", "kirim", "tautan", "direktori", "gửi", "thêm",
    "enviar", "adicionar", "aggiungi", "invia", "toevoegen", "indienen", "dodaj",
    "каталог", "добавить", "сайт", "dizin", "ekle", "ressource", "suggest a link",
)
NEGATIVE_HOST = (
    "duckduckgo.com", "bing.com", "mojeek.com", "google.", "yahoo.", "brave.com",
    "ecosia.org", "qwant.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "youtube.com", "youtu.be", "wikipedia.org", "reddit.com",
    "github.com", "tiktok.com", "pinterest.", "medium.com", "apps.apple.com",
    "play.google.com", "support.google.", "accounts.google.", "policies.google.",
)


def clean(raw: str) -> str:
    try:
        url = canonical_url(raw)
        if not url:
            return ""
        host = (urlparse(url).hostname or "").lower()
        if any(host == n.rstrip('.') or host.endswith(n) for n in NEGATIVE_HOST):
            return ""
        return url
    except Exception:
        return ""


def infer_evidence(title: str, url: str, query: str):
    hay = f"{title} {url} {query}".lower()
    score = sum(1 for term in TERMS if term in hay)
    method = "unknown"
    if "submit" in hay or "add" in hay or "suggest" in hay or "soumettre" in hay or "enviar" in hay or "提交" in hay or "送信" in hay or "제출" in hay:
        method = "form_or_submission_page"
    elif "directory" in hay or "resource" in hay or "catalog" in hay or "direktori" in hay or "annuaire" in hay:
        method = "directory_listing"
    return score, method


def main():
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise SystemExit("Playwright unavailable: " + type(e).__name__)

    db = load_db()
    errors = []
    pages = 0
    seen = set()
    max_pages = 120

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(locale="en-US")
        try:
            for category, language, query in QUERY_SPECS:
                for engine, template in ENGINES.items():
                    if pages >= max_pages:
                        break
                    try:
                        response = page.goto(template.format(q=quote_plus(query)), wait_until="domcontentloaded", timeout=15000)
                        pages += 1
                        body = ""
                        try:
                            body = page.locator("body").inner_text(timeout=2500).lower()
                        except Exception:
                            body = ""
                        if (response and response.status in (401, 403, 429)) or any(x in body for x in BLOCK):
                            errors.append(f"{engine}: challenged_or_rate_limited")
                            continue
                        links = page.locator("a[href]").evaluate_all(
                            "els=>els.map(a=>({url:a.href,title:(a.innerText||a.getAttribute('aria-label')||a.getAttribute('title')||'').trim()}))"
                        )
                        for item in links:
                            url = clean(item.get("url", ""))
                            title = (item.get("title") or "").strip()
                            if not url or url in seen:
                                continue
                            if len(title) < 3 and len(url) > 180:
                                continue
                            seen.add(url)
                            score, method = infer_evidence(title, url, query)
                            if score < 1:
                                continue
                            upsert_candidate(db, {
                                "url": url,
                                "title": title[:240],
                                "category": category,
                                "language": language,
                                "method": method,
                                "status": "discovered",
                                "source_engine": engine,
                                "source_query": query,
                                "evidence": {
                                    "discovery_score": score,
                                    "discovery_engine": engine,
                                    "discovery_query": query,
                                    "discovery_title": title[:240],
                                },
                                "reasons": ["discovered_from_search"],
                            }, history_reason="discovered")
                    except Exception as e:
                        errors.append(f"{engine}:{type(e).__name__}")
                if pages >= max_pages:
                    break
        finally:
            try:
                browser.close()
            except Exception:
                pass

    save_db(db)
    export = export_discovery_view(db, errors=errors, search_pages=pages, queries_configured=len(QUERY_SPECS))
    print(json.dumps({
        "mode": export["mode"],
        "queries_configured": export["queries_configured"],
        "search_pages": export["search_pages"],
        "candidate_count": export["candidate_count"],
        "errors": export["errors"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
