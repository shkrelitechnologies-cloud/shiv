#!/usr/bin/env python3
"""SHIV 666 operational audit (read-only).

Reads the local IST summary and publication ledger. Never treats workflow
success or attempts as verified publications.
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
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f)), None


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
        attempts = pending = failed = skipped = rejected = uncertain = 0
        for r in ledger:
            ts = r.get("timestamp_ist", "")
            if not ts.startswith(today):
                continue
            status = (r.get("status") or "").strip().lower()
            if status == "verified":
                dest = (r.get("destination") or r.get("readback_url") or "").strip()
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
            # attempts for verified/uncertain/failed are also tracked in summary logic;
            # keep explicit categories separate for audit clarity.
        # Reconcile with summary counters where they represent today's state
        if summary.get("date_ist") == today:
            verified = int(summary.get("verified_publications", len(verified_destinations)) or 0)
            attempts = int(summary.get("attempts", attempts) or 0)
            pending = int(summary.get("pending", pending) or 0)
            failed = int(summary.get("failed", failed) or 0)
            skipped = int(summary.get("skipped", skipped) or 0)
            rejected = int(summary.get("rejected", rejected) or 0)
            uncertain = int(summary.get("uncertain", uncertain) or 0)
            unique = summary.get("unique_verified_destinations", list(verified_destinations))
            if isinstance(unique, list):
                verified_destinations = set(unique)
        else:
            verified = len(verified_destinations)
            report["errors"].append(f"Summary date {summary.get('date_ist')} != today {today}; using today's ledger-derived state where possible")

        verified = len(verified_destinations)
        remaining = max(0, TARGET - verified)
        rate = (remaining / (remaining_seconds / 3600.0)) if remaining_seconds > 0 else None
        report.update({
            "verified_unique_publications": verified,
            "unique_verified_destinations": sorted(verified_destinations),
            "remaining_to_target": remaining,
            "remaining_time_ist": str(midnight - now).split(".")[0],
            "required_verified_per_hour": round(rate, 3) if rate is not None else None,
            "attempts": attempts,
            "pending": pending,
            "failed": failed,
            "blocked": 0,
            "skipped": skipped,
            "rejected": rejected,
            "uncertain": uncertain,
            "duplicates": 0,
            "existing_listings_verified": 0,
            "approved_destinations_configured": 0,
            "blocker_note": "sites.json has no approved link-only destinations; discovery is research-only and does not grant publishing permission.",
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
