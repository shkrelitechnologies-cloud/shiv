"""Shared constants and helpers for SHIV."""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PAYLOAD = "https://x.com/Shiv6xo/status/2103135286985420816?a=wXvMvt9e-Ph2h9Mqo48&s=19"
IST = ZoneInfo("Asia/Kolkata")
TARGET = 666
SITES_FILE = ROOT / "sites.json"
AUTO_ADAPTERS_FILE = ROOT / "operations" / "AUTO_ADAPTERS.json"
LEDGER_FILE = ROOT / "operations" / "PUBLICATION_LEDGER.csv"
SUMMARY_FILE = ROOT / "operations" / "DAILY_SUMMARY.json"
CANDIDATE_DB_FILE = ROOT / "operations" / "CANDIDATE_DB.json"
CANDIDATE_HISTORY_FILE = ROOT / "operations" / "CANDIDATE_HISTORY.jsonl"
DISCOVERY_EXPORT_FILE = ROOT / "operations" / "DISCOVERY_CANDIDATES.json"

BLOCK_TERMS = re.compile(
    r"\b(captcha|recaptcha|hcaptcha|verify you are human|security challenge|"
    r"sign in|log in|login required|create an account|register to|sign up to|"
    r"email verification|phone verification|verify your email|verify your phone|"
    r"payment required|subscribe to continue|human verification|cloudflare)\b", re.I
)
CAPTCHA_SELECTORS = [
    'iframe[src*="captcha"]', 'iframe[src*="recaptcha"]',
    'iframe[src*="hcaptcha"]', 'iframe[src*="turnstile"]',
    '[class*="captcha"]', '[id*="captcha"]', 'input[name*="captcha"]',
    '[data-sitekey]', '.cf-turnstile', '.g-recaptcha', '.h-captcha'
]

LEDGER_FIELDS = ["timestamp_ist", "site", "destination", "status", "detail", "payload", "readback_url"]


def now_ist() -> datetime:
    return datetime.now(timezone.utc).astimezone(IST)


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_ist() -> str:
    return now_ist().date().isoformat()


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def is_public_http(url: str) -> bool:
    try:
        p = urlparse(url or "")
        return p.scheme in ("http", "https") and bool(p.hostname) and not p.username and not p.password
    except Exception:
        return False


def canonical_url(url: str) -> str:
    try:
        p = urlparse((url or "").strip())
        if p.scheme not in ("http", "https") or not p.hostname:
            return ""
        host = p.hostname.lower().rstrip(".")
        path = p.path or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        return urlunparse((p.scheme.lower(), host + (":" + str(p.port) if p.port else ""), path, "", p.query, ""))
    except Exception:
        return ""


def domain_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().rstrip(".")
    except Exception:
        return ""


@dataclass
class Result:
    site: str
    destination: str
    status: str
    detail: str
    readback_url: str = ""
    evidence: dict = field(default_factory=dict)

    def to_ledger_row(self):
        return [now_ist().isoformat(), self.site, self.destination,
                self.status, self.detail, PAYLOAD, self.readback_url]


def append_ledger(result: Result):
    LEDGER_FILE.parent.mkdir(parents=True, exist_ok=True)
    new_file = not LEDGER_FILE.exists() or LEDGER_FILE.stat().st_size == 0
    with LEDGER_FILE.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(LEDGER_FIELDS)
        writer.writerow(result.to_ledger_row())


def append_candidate_history(event: dict):
    CANDIDATE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = dict(event)
    event.setdefault("timestamp_utc", now_utc_iso())
    with CANDIDATE_HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

