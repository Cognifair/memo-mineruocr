"""Offline behavioral checks. No real Token, cloud upload or OCR billing."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile

from pypdf import PdfReader, PdfWriter

SPEC = importlib.util.spec_from_file_location("workflow", Path(__file__).with_name("workflow.py"))
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)

COVERAGE_SPEC = importlib.util.spec_from_file_location("check_coverage",
                                                       Path(__file__).with_name("check_coverage.py"))
coverage = importlib.util.module_from_spec(COVERAGE_SPEC)
COVERAGE_SPEC.loader.exec_module(coverage)


class Response(io.BytesIO):
    status = 200


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "book.pdf"
        writer = PdfWriter()
        for number in range(7):
            writer.add_blank_page(width=400 + number, height=600)
        with self.source.open("wb") as stream:
            writer.write(stream)
        self.original = self.source.read_bytes()
        self.job = self.root / "job"
        w.prepare(self.source, self.job, max_pages=3)
        self.manifest = self.job / "manifest.json"

    def tearDown(self):
        self.temp.cleanup()

    def data(self):
        return json.loads(self.manifest.read_text())

    def results(self, markdown="![figure](images/same.png)\nText\n", extras=None):
        data = self.data()
        for chunk in data["chunks"]:
            target = self.job / "results" / (chunk["id"] + ".zip")
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("full.md", markdown)
                archive.writestr("images/same.png", b"different bytes: " + chunk["id"].encode())
                for name, content in (extras or {}).items():
                    archive.writestr(name, content)
            chunk.update(state="done", zip=target.relative_to(self.job).as_posix(), zip_sha256=w.sha(target))
        w.save(self.manifest, data)

    def test_split_has_exact_continuous_page_coverage_and_preserves_source(self):
        data = w.load(self.manifest)
        self.assertEqual([(c["start"], c["end"]) for c in data["chunks"]], [(1, 3), (4, 6), (7, 7)])
        widths = []
        for chunk in data["chunks"]:
            widths.extend(float(p.mediabox.width) for p in PdfReader(self.job / chunk["file"]).pages)
        self.assertEqual(widths, list(range(400, 407)))
        self.assertEqual(self.original, self.source.read_bytes())

    def test_byte_limit_recursively_splits_even_below_page_limit(self):
        job = self.root / "small-job"
        w.prepare(self.source, job, max_pages=200, max_mb=0.0008)
        data = w.load(job / "manifest.json")
        self.assertGreater(len(data["chunks"]), 1)
        self.assertTrue(all(c["bytes"] <= 800 for c in data["chunks"]))

    def test_single_page_oversize_stops_without_downsampling(self):
        with self.assertRaisesRegex(ValueError, "One page"):
            w.prepare(self.source, self.root / "too-small", max_mb=0.00001)
        self.assertEqual(self.original, self.source.read_bytes())

    def test_gap_and_changed_source_rejected(self):
        data = self.data()
        data["chunks"][1]["start"] += 1
        w.save(self.manifest, data)
        with self.assertRaisesRegex(ValueError, "cover"):
            w.load(self.manifest)
        data["chunks"][1]["start"] -= 1
        w.save(self.manifest, data)
        (self.job / data["chunks"][0]["file"]).write_bytes(b"altered")
        with self.assertRaisesRegex(ValueError, "changed"):
            w.load(self.manifest)

    def test_merge_renames_assets_and_keeps_source_order(self):
        self.results()
        output = self.root / "merged"
        w.merge(self.manifest, output)
        text = (output / "document.md").read_text()
        self.assertLess(text.index("Source pages 1-3"), text.index("Source pages 4-6"))
        for part in ("part-0001", "part-0002", "part-0003"):
            link = f"assets/{part}/images/same.png"
            self.assertIn(link, text)
            self.assertIn(part.encode(), (output / link).read_bytes())
        report = json.loads((output / "report.json").read_text())
        self.assertEqual(report["pages"], 7)
        self.assertEqual(report["status"], "complete")
        self.assertNotIn("batch_id", json.dumps(report))

    def test_html_reference_and_parent_relative_links(self):
        text, links, remote = w.rewrite_markdown(
            '<img src="../images/a%20b.png">\n![x][id]\n[id]: ../images/a%20b.png\n[site](https://example.com)',
            "doc/full.md", {"images/a b.png"}, "part-0001")
        self.assertEqual(len(links), 2)
        self.assertIn('src="assets/part-0001/images/a%20b.png"', text)
        self.assertEqual(remote, 1)

    def test_code_fence_not_rewritten(self):
        text = '```markdown\n![sample](not-real.png)\n```\nText'
        self.assertEqual(w.rewrite_markdown(text, "full.md", set(), "part-0001")[0], text)

    def test_missing_asset_prevents_output(self):
        self.results("![missing](missing.png)")
        output = self.root / "bad-output"
        with self.assertRaisesRegex(ValueError, "Missing"):
            w.merge(self.manifest, output)
        self.assertFalse(output.exists())

    def test_partial_result_is_not_complete(self):
        with self.assertRaisesRegex(ValueError, "All chunks"):
            w.merge(self.manifest, self.root / "partial")

    def test_zip_traversal_and_windows_ambiguity_are_rejected(self):
        for name in ("../escape", "/absolute", "C:/escape", "dir\\escape", "CON.png", "x.png.", "a//b", "./file"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                w.safe_member(name)
        self.results(extras={"../escape": b"bad"})
        with self.assertRaises(ValueError):
            w.merge(self.manifest, self.root / "unsafe")
        self.assertFalse((self.root / "escape").exists())

    def test_existing_output_never_overwritten(self):
        self.results()
        output = self.root / "existing"
        output.mkdir()
        (output / "keep").write_text("user content")
        with self.assertRaisesRegex(ValueError, "already exists"):
            w.merge(self.manifest, output)
        self.assertEqual((output / "keep").read_text(), "user content")

    def test_cloud_requires_upload_consent_and_token_before_network(self):
        with patch.object(w, "api") as called:
            with self.assertRaisesRegex(ValueError, "consent"):
                w.submit(self.manifest, "part-0001")
            with patch.dict(os.environ, {}, clear=True), patch.object(w, "get_secret", side_effect=w.SecretNotFound("missing")), self.assertRaisesRegex(ValueError, "MINERU_TOKEN"):
                w.submit(self.manifest, "part-0001", True)
            called.assert_not_called()
        self.assertEqual(self.data()["chunks"][0]["state"], "prepared")

    def test_submit_keeps_credentials_off_storage_and_does_not_repeat(self):
        fake_secret = "offline-test-secret"
        signed_url = "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?signature=local-test"
        with patch.dict(os.environ, {"MINERU_TOKEN": fake_secret}), patch.object(w, "api", return_value={
                "batch_id": "batch-test", "file_urls": [signed_url]}) as called, patch.object(w, "request", return_value=Response()) as put:
            w.submit(self.manifest, "part-0001", True)
            self.assertNotIn("Authorization", put.call_args.kwargs["headers"])
            result = w.submit(self.manifest, "part-0001", True)
            self.assertEqual(result["status"], "already_submitted")
            self.assertEqual(called.call_count, 1)
        persisted = self.manifest.read_text()
        self.assertNotIn(fake_secret, persisted)
        self.assertNotIn(signed_url, persisted)

    def test_uncertain_post_never_automatically_resubmitted(self):
        with patch.dict(os.environ, {"MINERU_TOKEN": "offline"}), patch.object(w, "api", side_effect=RuntimeError("offline failure")) as called:
            with self.assertRaises(RuntimeError):
                w.submit(self.manifest, "part-0001", True)
            with self.assertRaisesRegex(ValueError, "unknown"):
                w.submit(self.manifest, "part-0001", True)
            self.assertEqual(called.call_count, 1)

    def test_download_failure_is_resumable_without_upload(self):
        data = self.data()
        data["chunks"][0].update(batch_id="batch-test", state="submitted")
        w.save(self.manifest, data)
        row = {"extract_result": [{"data_id": "part-0001", "state": "done", "full_zip_url": "https://mineru.net/test.zip"}]}
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as archive:
            archive.writestr("full.md", "test content")
        with patch.dict(os.environ, {"MINERU_TOKEN": "offline"}), patch.object(w, "api", return_value=row) as called:
            with patch.object(w, "request", side_effect=RuntimeError("offline failure")), self.assertRaises(RuntimeError):
                w.collect(self.manifest, "part-0001")
            self.assertEqual(self.data()["chunks"][0]["state"], "download_pending")
            with patch.object(w, "request", return_value=Response(content.getvalue())):
                self.assertEqual(w.collect(self.manifest, "part-0001")["status"], "done")
            with patch.object(w, "request") as download:
                self.assertTrue(w.collect(self.manifest, "part-0001")["cached"])
                download.assert_not_called()
            self.assertEqual(called.call_count, 2)

    def test_only_verified_https_urls(self):
        for url in ("http://mineru.net/x", "https://mineru.net.evil.test/x", "https://u:p@mineru.net/x", "https://127.0.0.1/x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                w.safe_url(url)
        self.assertEqual(w.safe_url("https://cdn-mineru.openxlab.org.cn/x"), "https://cdn-mineru.openxlab.org.cn/x")

    def test_signed_upload_keeps_content_type_empty(self):
        # urllib injects 'application/x-www-form-urlencoded' for any request with a body; OSS signs
        # that header and answers 403 SignatureDoesNotMatch unless it stays explicitly empty.
        signed_url = "https://mineru.oss-cn-shanghai.aliyuncs.com/upload?signature=local-test"
        with patch.dict(os.environ, {"MINERU_TOKEN": "offline"}), patch.object(w, "api", return_value={
                "batch_id": "batch-test", "file_urls": [signed_url]}), patch.object(w, "request", return_value=Response()) as put:
            w.submit(self.manifest, "part-0001", True)
        headers = put.call_args.kwargs["headers"]
        self.assertEqual(headers.get("Content-Type"), "")
        self.assertNotIn("Authorization", headers)

    def test_waiting_file_batch_can_be_replaced_only_once_per_upload(self):
        data = self.data()
        data["chunks"][0].update(batch_id="batch-old", state="upload_unknown")
        w.save(self.manifest, data)
        with patch.dict(os.environ, {"MINERU_TOKEN": "offline"}), patch.object(w, "api", return_value={
                "batch_id": "batch-new", "file_urls": ["https://mineru.net/upload"]}), patch.object(w, "request", return_value=Response()):
            self.assertEqual(w.submit(self.manifest, "part-0001", True, "vlm", True)["status"], "submitted")
        chunk = self.data()["chunks"][0]
        self.assertEqual(chunk["batch_id"], "batch-new")
        self.assertEqual([entry["batch_id"] for entry in chunk["abandoned_batches"]], ["batch-old"])
        with patch.object(w, "api") as called, self.assertRaisesRegex(ValueError, "duplicate"):
            w.submit(self.manifest, "part-0001", True, "vlm", True)
        called.assert_not_called()
        self.assertEqual(self.data()["chunks"][0]["batch_id"], "batch-new")

    def test_replace_batch_rejected_after_upload_or_server_states(self):
        for state in ("submitted", "running", "converting", "download_pending", "done"):
            data = self.data()
            data["chunks"][0].update(batch_id="batch-old", state=state)
            w.save(self.manifest, data)
            with patch.object(w, "api") as called, self.assertRaises(ValueError):
                w.submit(self.manifest, "part-0001", True, "vlm", True)
            called.assert_not_called()
            self.assertEqual(self.data()["chunks"][0]["batch_id"], "batch-old")

    def test_no_proxy_override_bypasses_environment_proxies(self):
        def proxy_handlers(opener):
            return [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]

        self.addCleanup(setattr, w, "PROXY_OVERRIDE", None)
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://127.0.0.1:9"}):
            w.PROXY_OVERRIDE = None
            handlers = proxy_handlers(w.http_opener())
            self.assertEqual(len(handlers), 1)
            self.assertEqual(handlers[0].proxies.get("https"), "http://127.0.0.1:9")
            # urllib drops proxy handling entirely for an empty mapping: no proxy handler remains.
            w.PROXY_OVERRIDE = {}
            self.assertEqual(proxy_handlers(w.http_opener()), [])

    def test_cli_no_proxy_flag_sets_the_override(self):
        self.addCleanup(setattr, w, "PROXY_OVERRIDE", None)
        argv = ["workflow.py", "collect", str(self.manifest), "--chunk", "part-0001", "--no-proxy"]
        with patch.dict(os.environ, {"MINERU_TOKEN": "offline"}), patch.object(sys, "argv", argv), \
                patch.object(w, "collect", return_value={"status": "running"}), patch.object(sys, "stdout", io.StringIO()):
            self.assertEqual(w.main(), 0)
        self.assertEqual(w.PROXY_OVERRIDE, {})

    def test_api_rejection_reports_code_and_message(self):
        body = json.dumps({"code": -10001, "msg": "token invalid"}).encode()
        with patch.object(w, "request", return_value=Response(body)):
            with self.assertRaisesRegex(RuntimeError, "code=-10001.*token invalid"):
                w.api("/file-urls/batch", "offline-token")

    def test_transport_errors_name_the_host_and_mention_the_proxy(self):
        url = "https://mineru.oss-cn-shanghai.aliyuncs.com/upload"
        rejection = urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        with patch.object(w, "http_opener") as opener:
            opener.return_value.open.side_effect = rejection
            with self.assertRaisesRegex(RuntimeError, "HTTP 403 from mineru.oss-cn-shanghai.aliyuncs.com"):
                w.request(url)
            opener.return_value.open.side_effect = urllib.error.URLError("boom")
            with self.assertRaisesRegex(RuntimeError, "no-proxy"):
                w.request("https://mineru.net/api/v4/x")

    def test_coverage_check_flags_pages_without_content(self):
        data = self.data()
        chunk = data["chunks"][0]
        target = self.job / "results" / (chunk["id"] + ".zip")
        blocks = [{"page_idx": 0, "type": "text", "text": "x" * 50},
                  {"page_idx": 1, "type": "table", "text": "", "table_body": "<table></table>"}]
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("full.md", "x")
            archive.writestr("doc_content_list.json", json.dumps(blocks))
        chunk.update(state="done", zip=target.relative_to(self.job).as_posix(), zip_sha256=w.sha(target))
        w.save(self.manifest, data)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = coverage.report(self.manifest, 40, False)
        text = output.getvalue()
        self.assertEqual(status, 1)
        self.assertIn("PAGES WITH NO CONTENT: [3]", text)      # chunk p1-3, page_idx 2 is missing
        self.assertIn("tables: 1 blocks, 1 with HTML rows, 0 empty", text)
        self.assertIn("not collected yet", text)               # the other two chunks have no result

    def test_coverage_check_is_clean_when_every_page_returns_content(self):
        data = self.data()
        for index, chunk in enumerate(data["chunks"]):
            target = self.job / "results" / (chunk["id"] + ".zip")
            pages = chunk["end"] - chunk["start"] + 1
            blocks = [{"page_idx": page, "type": "text", "text": "y" * 60} for page in range(pages)]
            with zipfile.ZipFile(target, "w") as archive:
                archive.writestr("full.md", "x")
                archive.writestr(f"doc{index}_content_list.json", json.dumps(blocks))
            chunk.update(state="done", zip=target.relative_to(self.job).as_posix(), zip_sha256=w.sha(target))
        w.save(self.manifest, data)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(coverage.report(self.manifest, 40, False), 0)


if __name__ == "__main__":
    unittest.main()
