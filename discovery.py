#!/usr/bin/env python3
"""SHIV global multilingual destination research.

Research only: discovered pages are untrusted leads, never posting permission.
Only separately reviewed site-specific adapters may publish the exact SHIV URL.
"""
from __future__ import annotations
import json, re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus, urlparse, urlunparse

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"operations"/"DISCOVERY_CANDIDATES.json"
ENGINES={
 "duckduckgo":"https://html.duckduckgo.com/html/?q={q}",
 "bing":"https://www.bing.com/search?q={q}",
 "mojeek":"https://www.mojeek.com/search?q={q}",
 "yahoo":"https://search.yahoo.com/search?p={q}",
}
QUERIES=[
 "public directory submit a link link-only submission rules",
 "website add resource link submit URL public directory policy",
 "submit website link community resources public submission guidelines",
 "directorio enviar enlace añadir sitio reglas publicación",
 "soumettre un lien annuaire ajouter site règles",
 "Website Link einreichen Verzeichnis Richtlinien",
 "提交网站链接 目录 收录 规则",
 "ウェブサイト リンク 投稿 ディレクトリ 利用規約",
 "웹사이트 링크 제출 디렉토리 운영 정책",
 "إرسال رابط موقع دليل قواعد النشر",
 "वेबसाइट लिंक जमा निर्देशिका नियम",
 "kirim tautan situs direktori aturan pengiriman",
 "submit link public resource directory multilingual",
]
BLOCK=("captcha","verify you are human","unusual traffic","access denied","security check","robot check","sign in to continue")
TERMS=("submit","add link","add website","directory","resource","soumettre","enlace","verzeichnis","リンク","링크","رابط","वेबसाइट","direktori")

def clean(raw):
 try:
  p=urlparse(raw)
  if p.scheme not in ("http","https") or not p.hostname:return ""
  host=p.hostname.lower().rstrip(".")
  if host.endswith(("duckduckgo.com","bing.com","mojeek.com","google.com")):return ""
  if p.username or p.password:return ""
  return urlunparse((p.scheme,p.netloc,p.path or "/", "", "", ""))
 except Exception:return ""

def main():
 try:
  from playwright.sync_api import sync_playwright
 except Exception as e:
  raise SystemExit("Playwright unavailable: "+type(e).__name__)
 old=[]
 if OUT.exists():
  try: old=json.loads(OUT.read_text(encoding="utf-8"))
  except Exception: old=[]
 by={x.get("url"):x for x in old if isinstance(x,dict) and x.get("url")}
 errors=[]; pages=0; seen=set()
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True)
  page=browser.new_page(locale="en-US")
  for query in QUERIES:
   for engine,template in ENGINES.items():
    if pages>=80:break
    try:
     response=page.goto(template.format(q=quote_plus(query)),wait_until="domcontentloaded",timeout=15000)
     pages+=1
     body=page.locator("body").inner_text(timeout=2500).lower()
     if (response and response.status in (401,403,429)) or any(x in body for x in BLOCK):
      errors.append(engine+": challenged_or_rate_limited");continue
     links=page.locator("a[href]").evaluate_all("els=>els.map(a=>({url:a.href,title:(a.innerText||a.getAttribute('aria-label')||'').trim()}))")
     for item in links:
      url=clean(item.get("url",""));title=item.get("title","").strip()
      if not url or url in seen or len(title)<3:continue
      seen.add(url)
      score=sum(term in (title+" "+url).lower() for term in TERMS)
      if score<1:continue
      by[url]={"url":url,"title":title[:240],"source_engine":engine,"source_query":query,
       "first_seen_utc":datetime.now(timezone.utc).isoformat(),
       "state":"RESEARCH_ONLY","permission_verified":False,
       "next_step":"inspect official rules and submission method; do not submit from discovery alone"}
    except Exception as e:errors.append(engine+":"+type(e).__name__)
   if pages>=80:break
  browser.close()
 OUT.parent.mkdir(parents=True,exist_ok=True)
 data={"updated_utc":datetime.now(timezone.utc).isoformat(),"mode":"research_only",
  "queries_configured":len(QUERIES),"search_pages":pages,"candidate_count":len(by),
  "candidates":list(by.values())[-2000:],"errors":errors[-80:]}
 tmp=OUT.with_suffix(".json.tmp");tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf-8");tmp.replace(OUT)
 print(json.dumps({k:data[k] for k in ("mode","queries_configured","search_pages","candidate_count","errors")}))
if __name__=="__main__":main()
