#!/usr/bin/env python3
"""SHIV 666 operational audit (read-only).

Reads the local IST summary, publication ledger, candidate DB, and adapter
configuration. Never treats workflow success or attempts as verified publications.
"""
from __future__ import annotations

import csv
import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TZ = timezone(timedelta(hours=5, minutes=30))
TARGET = 666


def now_ist():
    return datetime.now(timezone.utc).astimezone(TZ)


def load_json(path: Path):
    if not path.exists():
        return None, f"missing:{path}"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:
        return None, f"invalid:{path}:{e}"


def gh_json(args):
    if not shutil.which("gh"):
        return None, "gh unavailable"
    try:
        out = subprocess.check_output(["gh", *args], cwd=ROOT, text=True, stderr=subprocess.STDOUT, timeout=20)
        return out.strip(), None
    except Exception as e:
        return None, str(e)


def read_ledger(path: Path):
    if not path.exists():
        return None, f"missing:{path}"
    try:
        with path.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f)), None
    except Exception as e:
        return None, f"invalid:{path}:{e}"


def count_configured():
    configured = 0
    auto_adapters = 0
    try:
        sites = load_json(ROOT / "sites.json")[0]
        if isinstance(sites, list):
            for s in sites:
                if not isinstance(s, dict) or s.get("_instructions"):
                    continue
                if all(s.get(k) for k in ("url", "input_selector", "submit_selector", "readback_url")):
                    if s.get("auto_discovered"):
                        auto_adapters += 1
                    elif s.get("permission_reviewed") and s.get("relevance_reviewed") and s.get("allows_link_only"):
                        configured += 1
    except Exception:
        pass
    try:
        aa = load_json(ROOT / "operations" / "AUTO_ADAPTERS.json")[0]
        adapters = aa.get("adapters", []) if isinstance(aa, dict) else (aa if isinstance(aa, list) else [])
        for a in adapters:
            if isinstance(a, dict) and all(a.get(k) for k in ("url", "input_selector", "submit_selector", "readback_url")):
                auto_adapters += 1
    except Exception:
        pass
    return configured, auto_adapters


def candidate_stats():
    db, err = load_json(ROOT / "operations" / "CANDIDATE_DB.json")
    if not isinstance(db, dict):
        return {"error": err} if err else {"error": "missing_or_invalid"}
    cands = db.get("candidates", {}) or {}
    by_status = {}
    for c in cands.values():
        st = (c or {}).get("status", "unknown")
        by_status[st] = by_status.get(st, 0) + 1
    return {"total": len(cands), "by_status": by_status}


def main():
    now = now_ist()
    today = now.date().isoformat()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    remaining_seconds = max(0.0, (midnight - now).total_seconds())

    summary, summary_err = load_json(ROOT / "operations" / "DAILY_SUMMARY.json")
    ledger, ledger_err = read_ledger(ROOT / "operations" / "PUBLICATION_LEDGER.csv")

    report = {
        "project": "SHIV",
        "repository": "shkrelitechnologies-cloud/shiv",
        "checked_at_ist": now.isoformat(timespec="seconds"),
        "today_ist": today,
        "target": TARGET,
        "ledger_source": "operations/DAILY_SUMMARY.json + operations/PUBLICATION_LEDGER.csv",
        "errors": [e for e in (summary_err, ledger_err) if e],
    }

    if summary is None or ledger is None:
        report.update({
            "verified_publications": "unverifiable",
            "remaining_to_target": "unverifiable",
            "required_rate_per_hour": "unverifiable",
            "note": "Ledger unavailable or unreadable; count is not reported as zero.",
        })
    else:
        verified_destinations = set()
        attempts = pending = failed = skipped = rejected = uncertain = duplicates = blocked = 0
        for r in ledger:
            ts = r.get("timestamp_ist", "")
            if not ts.startswith(today):
                continue
            status = (r.get("status") or "").strip().lower()
            dest = (r.get("readback_url") or r.get("destination") or "").strip()
            if status == "verified":
                if dest:
                    verified_destinations.add(dest)
            elif status in ("attempted",):
                attempts += 1
            elif status == "pending":
                pending += 1
            elif status == "failed":
                failed += 1
            elif status == "skipped":
                skipped += 1
            elif status == "rejected":
                rejected += 1
            elif status == "uncertain":
                uncertain += 1
            elif status == "duplicate":
                duplicates += 1
            elif status == "blocked":
                blocked += 1

        if isinstance(summary, dict) and summary.get("date_ist") == today:
            unique = summary.get("unique_verified_destinations", list(verified_destinations))
            if isinstance(unique, list):
                verified_destinations = set(unique)
            attempts = int(summary.get("attempts", attempts) or 0)
            pending = int(summary.get("pending", pending) or 0)
            failed = int(summary.get("failed", failed) or 0)
            skipped = int(summary.get("skipped", skipped) or 0)
            rejected = int(summary.get("rejected", rejected) or 0)
            uncertain = int(summary.get("uncertain", uncertain) or 0)
            duplicates = int(summary.get("duplicates", duplicates) or 0)
            blocked = int(summary.get("blocked", blocked) or 0)
        else:
            report["errors"].append(f"Summary date {summary.get('date_ist') if isinstance(summary, dict) else None} != today {today}; using today's ledger-derived state where possible")

        verified = len(verified_destinations)
        remaining = max(0, TARGET - verified)
        rate = (remaining / (remaining_seconds / 3600.0)) if remaining_seconds > 0 else None
        configured, auto_adapters = count_configured()
        report.update({
            "verified_unique_publications": verified,
            "unique_verified_destinations": sorted(verified_destinations),
            "remaining_to_target": remaining,
            "remaining_time_ist": str(midnight - now).split(".")[0],
            "required_verified_per_hour": round(rate, 3) if rate is not None else None,
            "attempts": attempts,
            "pending": pending,
            "failed": failed,
            "blocked": blocked,
            "skipped": skipped,
            "rejected": rejected,
            "uncertain": uncertain,
            "duplicates": duplicates,
            "existing_listings_verified": 0,
            "approved_destinations_configured": configured,
            "auto_adapters_configured": auto_adapters,
            "candidate_pipeline": candidate_stats(),
            "blocker_note": (
                "No manually approved destinations and no auto-discovered adapters yet; "
                "discovery/eligibility pipeline is active but only evidence-eligible, link-only, "
                "barrier-free forms with independent public readback can be counted."
                if (configured + auto_adapters) == 0 else
                "Only evidence-eligible, link-only, barrier-free submissions with independent public readback are counted."
            ),
        })

    runs_out, runs_err = gh_json(["run", "list", "-R", "shkrelitechnologies-cloud/shiv", "--limit", "5"])
    if runs_out is not None:
        report["recent_runs"] = runs_out.splitlines()[:5]
    else:
        report["recent_runs_error"] = runs_err

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
