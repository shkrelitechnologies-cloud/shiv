import csv
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

import auto_pipeline
import candidate_store
import common
import discovery
import ops_666
import shiv


IST = ZoneInfo("Asia/Kolkata")


class TestCommon(unittest.TestCase):
    def test_canonical_url_normalizes(self):
        self.assertEqual(common.canonical_url("HTTPS://Example.com:443/path/?a=1#x"), "https://example.com:443/path?a=1")
        self.assertEqual(common.canonical_url("http://example.com"), "http://example.com/")
        self.assertEqual(common.canonical_url("not a url"), "")

    def test_is_public_http(self):
        self.assertTrue(common.is_public_http("https://example.com/form"))
        self.assertFalse(common.is_public_http("ftp://example.com/x"))
        self.assertFalse(common.is_public_http("http://user:pass@example.com/"))
        self.assertFalse(common.is_public_http(""))


class TestCandidateStore(unittest.TestCase):
    def test_upsert_and_status_history(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "CANDIDATE_DB.json"
            hist_path = Path(td) / "CANDIDATE_HISTORY.jsonl"
            with mock.patch.object(candidate_store, "CANDIDATE_DB_FILE", db_path), \
                 mock.patch.object(candidate_store, "CANDIDATE_HISTORY_FILE", hist_path), \
                 mock.patch.object(candidate_store, "DISCOVERY_EXPORT_FILE", Path(td) / "DISCOVERY_CANDIDATES.json"), \
                 mock.patch.object(common, "CANDIDATE_HISTORY_FILE", hist_path):
                db = candidate_store.load_db()
                url = candidate_store.upsert_candidate(db, {
                    "url": "https://Example.com/submit/",
                    "title": "Submit site",
                    "category": "directory",
                    "language": "en",
                    "method": "form_or_submission_page",
                    "evidence": {"discovery_score": 2},
                    "status": "discovered",
                }, history_reason="discovered")
                self.assertEqual(url, "https://example.com/submit")
                self.assertIn(url, db["candidates"])
                rec = db["candidates"][url]
                self.assertEqual(rec["category"], "directory")
                self.assertEqual(rec["language"], "en")
                self.assertEqual(rec["status"], "discovered")
                candidate_store.set_status(db, url, "skipped", "no_eligible_link_only_form", last_result="no_eligible_link_only_form")
                self.assertEqual(db["candidates"][url]["status"], "skipped")
                candidate_store.save_db(db)
                self.assertTrue(db_path.exists())
                lines = hist_path.read_text(encoding="utf-8").strip().splitlines()
                self.assertGreaterEqual(len(lines), 2)
                events = [json.loads(x) for x in lines]
                self.assertTrue(any(e.get("to_status") == "skipped" for e in events))


class TestDiscoveryHelpers(unittest.TestCase):
    def test_clean_rejects_search_hosts_and_accepts_candidate(self):
        self.assertEqual(discovery.clean("https://www.bing.com/search?q=x"), "")
        self.assertEqual(discovery.clean("https://twitter.com/some"), "")
        self.assertTrue(discovery.clean("https://example-directory.org/submit").startswith("https://example-directory.org"))

    def test_infer_evidence(self):
        score, method = discovery.infer_evidence("Submit your website URL", "https://example.org/add-url", "submit site")
        self.assertGreaterEqual(score, 1)
        self.assertEqual(method, "form_or_submission_page")


class TestAutoPipelineHeuristics(unittest.TestCase):
    def test_evidence_eligible_context(self):
        ok, reason = auto_pipeline.evidence_eligible_context({"has_submit_language": True, "has_directory_context": False, "has_negative_context": False})
        self.assertTrue(ok)
        ok, reason = auto_pipeline.evidence_eligible_context({"has_submit_language": False, "has_directory_context": False, "has_negative_context": True})
        self.assertFalse(ok)
        self.assertEqual(reason, "negative_or_unrelated_context")

    def test_is_url_candidate(self):
        self.assertTrue(auto_pipeline.is_url_candidate({"tag": "input", "type": "url", "name": "site", "id": "", "placeholder": "", "label": ""}))
        self.assertTrue(auto_pipeline.is_url_candidate({"tag": "input", "type": "text", "name": "website_url", "id": "", "placeholder": "", "label": ""}))
        self.assertFalse(auto_pipeline.is_url_candidate({"tag": "input", "type": "email", "name": "email", "id": "", "placeholder": "", "label": "Email"}))
        self.assertFalse(auto_pipeline.is_url_candidate({"tag": "input", "type": "hidden", "name": "url", "id": "", "placeholder": "", "label": ""}))


class TestShivConfigAndSummary(unittest.TestCase):
    def test_eligible_configured_manual_and_auto(self):
        ok, reason = shiv.eligible_configured({
            "name": "x", "url": "https://example.com/submit",
            "permission_reviewed": True, "relevance_reviewed": True, "allows_link_only": True,
            "input_selector": "input[name=url]", "submit_selector": "button[type=submit]",
            "readback_url": "https://example.com/list"
        })
        self.assertTrue(ok)
        ok, reason = shiv.eligible_configured({"name": "x", "url": "https://example.com/submit", "allows_link_only": True, "input_selector": "i", "submit_selector": "s", "readback_url": "https://example.com/r"})
        self.assertFalse(ok)
        ok, reason = shiv.eligible_configured({
            "name": "auto", "url": "https://example.com/submit", "auto_discovered": True, "allows_link_only": True,
            "input_selector": "input[name=url]", "submit_selector": "button", "readback_url": "https://example.com/r"
        })
        self.assertTrue(ok)

    def test_write_summary_resets_on_new_ist_day_and_counts(self):
        with tempfile.TemporaryDirectory() as td:
            summary_path = Path(td) / "DAILY_SUMMARY.json"
            ledger_path = Path(td) / "PUBLICATION_LEDGER.csv"
            ledger_path.write_text("timestamp_ist,site,destination,status,detail,payload,readback_url\n", encoding="utf-8")
            old = {
                "date_ist": "2026-11-19", "target": 666, "verified_publications": 3,
                "unique_verified_destinations": ["https://old.example/"], "attempts": 5,
                "pending": 1, "rejected": 1, "skipped": 1, "failed": 1, "uncertain": 1,
            }
            summary_path.write_text(json.dumps(old), encoding="utf-8")
            fixed_now = datetime(2026, 11, 20, 10, 0, tzinfo=IST)
            results = [
                common.Result("s1", "https://a.example/submit", "verified", "ok", "https://a.example/list"),
                common.Result("s2", "https://b.example/submit", "uncertain", "submission_not_independently_verified", "https://b.example/list"),
                common.Result("s3", "https://c.example/submit", "duplicate", "already_verified_today", "https://c.example/list"),
                common.Result("s4", "https://d.example/submit", "skipped", "captcha_or_human_verification", "https://d.example/list"),
            ]
            with mock.patch.object(shiv, "SUMMARY_FILE", summary_path), \
                 mock.patch.object(shiv, "LEDGER_FILE", ledger_path), \
                 mock.patch.object(common, "SUMMARY_FILE", summary_path), \
                 mock.patch.object(common, "LEDGER_FILE", ledger_path), \
                 mock.patch.object(shiv, "now_ist", return_value=fixed_now):
                out = shiv.write_summary(results)
            self.assertEqual(out["date_ist"], "2026-11-20")
            self.assertEqual(out["verified_publications"], 1)
            self.assertEqual(out["attempts"], 2)  # verified + uncertain
            self.assertEqual(out["uncertain"], 1)
            self.assertEqual(out["skipped"], 1)
            self.assertEqual(out["duplicates"], 1)
            self.assertEqual(out["remaining"], 665)

    def test_duplicate_prevention_selection(self):
        db = {"candidates": {
            "https://example.com/a": {"url": "https://example.com/a", "status": "discovered"},
            "https://example.com/b": {"url": "https://example.com/b", "status": "verified"},
            "https://example.com/c": {"url": "https://example.com/c", "status": "skipped", "reasons": ["login_or_verification_barrier"], "last_result": "login_or_verification_barrier"},
        }}
        selected = shiv.select_auto_candidates(db, {"https://example.com/a"})
        urls = [c["url"] for c in selected]
        self.assertNotIn("https://example.com/a", urls)
        self.assertNotIn("https://example.com/b", urls)
        self.assertNotIn("https://example.com/c", urls)


class TestOps666(unittest.TestCase):
    def test_ops_666_read_only_report(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            ops = root / "operations"
            ops.mkdir()
            (ops / "DAILY_SUMMARY.json").write_text(json.dumps({
                "date_ist": "2026-11-20", "target": 666, "verified_publications": 1,
                "unique_verified_destinations": ["https://readback.example/item1"],
                "attempts": 2, "pending": 0, "rejected": 0, "skipped": 1, "failed": 0,
                "uncertain": 1, "duplicates": 0, "blocked": 0
            }), encoding="utf-8")
            with (ops / "PUBLICATION_LEDGER.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(["timestamp_ist", "site", "destination", "status", "detail", "payload", "readback_url"])
                w.writerow(["2026-11-20T10:00:00+05:30", "s", "https://dest", "verified", "ok", common.PAYLOAD, "https://readback.example/item1"])
            (root / "sites.json").write_text("[]", encoding="utf-8")
            (ops / "CANDIDATE_DB.json").write_text(json.dumps({"candidates": {"https://c.example": {"status": "discovered"}}}), encoding="utf-8")
            fixed_now = datetime(2026, 11, 20, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
            with mock.patch.object(ops_666, "ROOT", root), \
                 mock.patch.object(ops_666, "now_ist", return_value=fixed_now), \
                 mock.patch.object(ops_666, "gh_json", return_value=("run1", None)):
                buf = io.StringIO()
                old = sys.stdout
                sys.stdout = buf
                try:
                    rc = ops_666.main()
                finally:
                    sys.stdout = old
                self.assertEqual(rc, 0)
                report = json.loads(buf.getvalue())
            self.assertEqual(report["verified_unique_publications"], 1)
            self.assertEqual(report["remaining_to_target"], 665)
            self.assertIn("candidate_pipeline", report)
            self.assertEqual(report["candidate_pipeline"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
