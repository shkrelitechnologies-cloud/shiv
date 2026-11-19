#!/usr/bin/env python3
"""SHIV 15-minute watchdog for its bounded Playwright publisher workflow.

Re-enables a disabled workflow where GitHub permits it, avoids duplicate active
runs, requests cancellation of stale runs, and dispatches one recovery run when
the last successful run is stale. It never changes payloads or site permissions.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://api.github.com"
WORKFLOW = "shiv.yml"
BRANCH = "main"
STALE_ACTIVE_MINUTES = 25
STALE_QUEUED_MINUTES = 20
SUCCESS_STALE_MINUTES = 45
REPORT = Path("state/shiv-watchdog.json")


def request(method: str, url: str, token: str, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "SHIV-Actions-Watchdog",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        body = response.read()
        return json.loads(body) if body else {"http_status": response.status}


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN", "")
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    now = datetime.now(timezone.utc)
    result = {
        "checked_at_utc": now.isoformat(),
        "repository": repository,
        "workflow": WORKFLOW,
        "status": "unknown",
        "active_runs": 0,
        "last_success_age_minutes": None,
        "actions": [],
        "errors": [],
    }
    try:
        if not token or "/" not in repository:
            raise RuntimeError("GITHUB_TOKEN or GITHUB_REPOSITORY is unavailable")

        base = f"{API}/repos/{repository}/actions/workflows/{WORKFLOW}"
        workflow = request("GET", base, token)
        if workflow.get("state") != "active":
            request("PUT", base + "/enable", token)
            result["actions"].append("Requested workflow re-enable")
        else:
            result["actions"].append("Publisher workflow is enabled")

        runs_url = f"{base}/runs?branch={BRANCH}&per_page=30"
        runs = request("GET", runs_url, token).get("workflow_runs", [])
        active = [run for run in runs if run.get("status") in {"queued", "in_progress"}]
        result["active_runs"] = len(active)

        successful_times = [
            parse_time(run.get("updated_at") or run.get("completed_at") or run["created_at"])
            for run in runs
            if run.get("conclusion") == "success" and
            (run.get("updated_at") or run.get("completed_at") or run.get("created_at"))
        ]
        last_success = max(successful_times) if successful_times else None
        age = (now - last_success).total_seconds() / 60 if last_success else None
        result["last_success_age_minutes"] = round(age, 1) if age is not None else None

        stale = []
        for run in active:
            created = parse_time(run["created_at"])
            limit = STALE_ACTIVE_MINUTES if run["status"] == "in_progress" else STALE_QUEUED_MINUTES
            if (now - created).total_seconds() / 60 > limit:
                stale.append(run)
        if stale:
            for run in stale:
                request("POST", f"{API}/repos/{repository}/actions/runs/{run['id']}/cancel", token)
            result["status"] = "stale_run_cancel_requested"
            result["stale_run_ids"] = [run["id"] for run in stale]
            result["actions"].append("Requested cancellation of stale run(s); recovery waits for the next watchdog cycle")
        elif active:
            result["status"] = "healthy_active"
            result["actions"].append("A publisher run is already active; duplicate dispatch avoided")
        elif age is None or age > SUCCESS_STALE_MINUTES:
            request("POST", base + "/dispatches", token, {"ref": BRANCH})
            result["status"] = "recovery_dispatched"
            result["actions"].append("Dispatched one recovery run because the last successful run is stale")
        else:
            result["status"] = "healthy"
            result["actions"].append("Recent successful publisher run found")
    except urllib.error.HTTPError as exc:
        result["status"] = "blocked"
        result["errors"].append(f"GitHub API HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:1500]}")
    except Exception as exc:
        result["status"] = "blocked"
        result["errors"].append(f"{type(exc).__name__}: {exc}")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
