"""Offline behavioral checks. No real Token, cloud upload or OCR billing."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from pypdf import PdfReader, PdfWriter

SPEC = importlib.util.spec_from_file_location("workflow", Path(__file__).with_name("workflow.py"))
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)


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
            with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "MINERU_TOKEN"):
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


if __name__ == "__main__":
    unittest.main()
