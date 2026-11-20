"""Persistent candidate store for SHIV discovery and submission pipeline."""
from __future__ import annotations

from typing import Any

from common import (
    CANDIDATE_DB_FILE, CANDIDATE_HISTORY_FILE, DISCOVERY_EXPORT_FILE,
    append_candidate_history, canonical_url, domain_of, now_utc_iso, read_json, write_json_atomic,
)

EMPTY_DB = {"version": 1, "updated_utc": None, "candidates": {}}


def load_db() -> dict[str, Any]:
    data = read_json(CANDIDATE_DB_FILE, None)
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), dict):
        return {"version": 1, "updated_utc": None, "candidates": {}}
    data.setdefault("version", 1)
    return data


def save_db(db: dict[str, Any]):
    db["updated_utc"] = now_utc_iso()
    write_json_atomic(CANDIDATE_DB_FILE, db)


def upsert_candidate(db: dict[str, Any], record: dict[str, Any], history_reason: str = "") -> str:
    url = canonical_url(record.get("url", ""))
    if not url:
        return ""
    candidates = db.setdefault("candidates", {})
    now = now_utc_iso()
    existing = candidates.get(url, {})
    merged = dict(existing)
    for k, v in record.items():
        if v is None or v == "" or v == [] or v == {}:
            continue
        if k == "evidence" and isinstance(v, dict):
            ev = dict(existing.get("evidence") or {})
            ev.update(v)
            merged["evidence"] = ev
            continue
        if k == "reasons" and isinstance(v, list):
            reasons = list(existing.get("reasons") or [])
            for r in v:
                if r and r not in reasons:
                    reasons.append(r)
            merged["reasons"] = reasons[-20:]
            continue
        merged[k] = v
    merged["url"] = url
    merged["domain"] = merged.get("domain") or domain_of(url)
    merged.setdefault("first_seen_utc", existing.get("first_seen_utc") or now)
    merged["last_seen_utc"] = now
    merged.setdefault("status", "discovered")
    merged.setdefault("category", "unknown")
    merged.setdefault("language", "unknown")
    merged.setdefault("method", "unknown")
    merged.setdefault("evidence", {})
    merged.setdefault("reasons", [])
    old_status = existing.get("status")
    candidates[url] = merged
    if history_reason or old_status != merged.get("status"):
        append_candidate_history({
            "url": url,
            "from_status": old_status,
            "to_status": merged.get("status"),
            "reason": history_reason or "upsert",
            "detail": merged.get("last_result") or "",
        })
    return url


def set_status(db: dict[str, Any], url: str, status: str, reason: str = "", **fields):
    url = canonical_url(url)
    if not url or url not in db.get("candidates", {}):
        return
    rec = db["candidates"][url]
    old = rec.get("status")
    rec["status"] = status
    if reason:
        reasons = list(rec.get("reasons") or [])
        if reason not in reasons:
            reasons.append(reason)
        rec["reasons"] = reasons[-20:]
    rec.update({k: v for k, v in fields.items() if v is not None})
    rec["last_checked_utc"] = now_utc_iso()
    if old != status or reason:
        append_candidate_history({
            "url": url,
            "from_status": old,
            "to_status": status,
            "reason": reason,
            "detail": rec.get("last_result") or "",
        })


def export_discovery_view(db: dict[str, Any], errors=None, search_pages: int = 0, queries_configured: int = 0):
    candidates = list(db.get("candidates", {}).values())
    candidates.sort(key=lambda x: (x.get("first_seen_utc") or "", x.get("url") or ""))
    # keep a bounded export for readability
    export = {
        "updated_utc": db.get("updated_utc") or now_utc_iso(),
        "mode": "research_and_evidence_pipeline",
        "queries_configured": queries_configured,
        "search_pages": search_pages,
        "candidate_count": len(candidates),
        "candidates": candidates[-2000:],
        "errors": (errors or [])[-120:],
    }
    write_json_atomic(DISCOVERY_EXPORT_FILE, export)
    return export

