import base64
import re
from hashlib import sha256
from io import BytesIO
import json
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zipfile import ZipFile

import httpx
from fastapi.testclient import TestClient
from app import app, SPEC


def response(payload, status=200):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", "http://team.example/process"))


def completed():
    content = b"%PDF-1.4\nexample bytes"
    pdf = {"file_name": "sample_EDITED.pdf", "media_type": "application/pdf", "sha256": sha256(content).hexdigest(), "modified": False, "content_base64": base64.b64encode(content).decode()}
    return {"evaluation_id": str(uuid4()), "status": "completed", "input": {"file_name": "sample.pdf", "sha256": sha256(content).hexdigest(), "size_bytes": len(content)}, "outcome": "completed_no_repairs", "checks_performed": [], "findings": [], "repairs": [], "new_issues_after_repair": [], "human_review_items": [], "summary": {"total_issues": 0, "fixed_count": 0, "human_review_count": 0}, "limitations": ["Validation only; accessibility checks not performed."], "compliance_statement": "This report does not certify ADA Title II or WCAG 2.1 conformance.", "output_pdf": pdf, "report_pdf": {**pdf, "file_name": "sample_report.pdf"}}


class InterfaceContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def upload(self, path="/api/team3/process", content=b"original", filename="sample.pdf", data=None):
        return self.client.post(path, files={"file": (filename, content, "application/octet-stream")}, data=data)

    def test_proxy_builds_zip_from_standard_completed_json(self):
        payload = completed()
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response(payload)) as post:
            result = self.upload(content=b"%PDF-1.4\nexample bytes")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(post.await_args.kwargs["headers"]["Accept"], "application/json")
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"report.json", "sample.pdf", "sample_EDITED.pdf", "sample_report.pdf"})
            self.assertEqual(archive.read("sample.pdf"), b"%PDF-1.4\nexample bytes")
            self.assertEqual(json.loads(archive.read("report.json")), payload)

    def test_proxy_error_zip_has_only_original_and_json(self):
        payload = {"status": "error", "error_code": "INVALID_FILE_TYPE", "message": "Input must be a PDF."}
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response(payload, 415)):
            result = self.upload(content=b"text", filename="notes.txt")
        self.assertEqual(result.status_code, 200)
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"report.json", "notes.txt"})
            self.assertEqual(archive.read("notes.txt"), b"text")

    def test_proxy_rejects_old_schema_and_bad_pdf_hash(self):
        bad_hash = completed()
        bad_hash["output_pdf"]["sha256"] = "wrong"
        for payload in [{"status": "accepted"}, bad_hash]:
            with self.subTest(payload=payload["status"]):
                with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response(payload)):
                    self.assertEqual(self.upload().status_code, 502)

    def test_proxy_reports_external_failure(self):
        payload = {"status": "error", "error_code": "EXTERNAL_SERVICE_UNAVAILABLE", "message": "Unavailable"}
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response(payload, 503)):
            self.assertEqual(self.upload().status_code, 502)

    def test_comparison_runs_session_workflow_and_forwards_all_file_types(self):
        sessions = []
        async def post(url, **kwargs):
            if url.endswith("/test/setup"):
                self.assertEqual(kwargs["timeout"], 10.0)
                session = kwargs["json"]["session_id"]
                sessions.append(session)
                return response({"session_id": session}, 201)
            self.assertIn(kwargs["data"]["session_id"], sessions)
            self.assertEqual(kwargs["files"]["file"], ("notes.txt", b"text", "application/octet-stream"))
            return response({"status": "error", "error_code": "INVALID_FILE_TYPE", "message": "Not PDF"}, 415)
        async def get(url, **kwargs):
            if url.endswith("/health"):
                return response({"status": "ok", "spec_version": "0.3.0"})
            if url.endswith("/checks"):
                return response({"checks": []})
            return response({"session_id": kwargs["params"]["session_id"], "coverage": {"code": {"covered": None, "total": None, "basis": "Unavailable"}}})
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=post), patch("app.httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=get):
            result = self.upload("/api/compare", b"text", "notes.txt", {"team_a_url": "http://team-a", "team_b_url": "http://team-b"}).json()
        self.assertEqual(len(set(sessions)), 2)
        for key in ("team_a", "team_b"):
            self.assertTrue(result[key]["contract_valid"])
            self.assertFalse(result[key]["success"])
            self.assertEqual(result[key]["body"]["error_code"], "INVALID_FILE_TYPE")

    def test_failed_setup_does_not_run_project_calls(self):
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response({"source": "system", "message": "Setup failed"}, 500)) as post, patch("app.httpx.AsyncClient.get", new_callable=AsyncMock) as get:
            result = self.upload("/api/compare", data={"team_a_url": "http://a", "team_b_url": "http://b"}).json()
        self.assertEqual(post.await_count, 2)
        self.assertEqual(get.await_count, 0)
        self.assertFalse(result["team_a"]["success"])

    def test_timeout_is_communication_error_without_retries(self):
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ReadTimeout("Timed out")) as post:
            result = self.upload("/api/compare", data={"team_a_url": "http://a", "team_b_url": "http://b"}).json()
        self.assertEqual(post.await_count, 2)
        self.assertEqual(result["team_a"]["source"], "communication")
        self.assertEqual(result["team_a"]["outcome"], "error")


class UnifiedDownloadTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def download(self, payload, content=b"%PDF-1.4\nexample bytes", filename="sample.pdf"):
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return self.client.post("/api/review-download", files={"file": (filename, content, "application/octet-stream"), "report": ("report.json", raw, "application/json")})

    def test_exact_result_is_packaged_without_rerunning_team(self):
        payload = completed()
        with patch("app.httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            result = self.download(payload)
        self.assertEqual(result.status_code, 200)
        post.assert_not_awaited()
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"report.json", "sample.pdf", "sample_EDITED.pdf", "sample_report.pdf"})
            self.assertEqual(json.loads(archive.read("report.json")), payload)
            self.assertEqual(archive.read("sample.pdf"), b"%PDF-1.4\nexample bytes")

    def test_rejected_result_has_only_original_and_json(self):
        payload = {"status": "error", "error_code": "INVALID_FILE_TYPE", "message": "Not PDF"}
        result = self.download(payload, b"text", "notes.txt")
        self.assertEqual(result.status_code, 200)
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"report.json", "notes.txt"})
            self.assertEqual(json.loads(archive.read("report.json")), payload)

    def test_invalid_json_or_contract_is_rejected(self):
        for value in [b"not JSON", [], {"status": "accepted"}]:
            with self.subTest(value=value):
                self.assertEqual(self.download(value).status_code, 400)

    def test_wrong_original_or_corrupt_pdf_is_rejected(self):
        self.assertEqual(self.download(completed(), b"different original").status_code, 400)
        payload = completed()
        payload["report_pdf"]["sha256"] = "wrong"
        self.assertEqual(self.download(payload).status_code, 400)

    def test_report_filename_collision_preserves_both(self):
        payload = {"status": "error", "error_code": "INVALID_FILE_TYPE", "message": "Not PDF"}
        result = self.download(payload, b"original JSON bytes", "report.json")
        with ZipFile(BytesIO(result.content)) as archive:
            self.assertEqual(set(archive.namelist()), {"report.json", "original/report.json"})
            self.assertEqual(archive.read("original/report.json"), b"original JSON bytes")

    def test_page_has_one_file_picker_and_both_result_sections(self):
        page = self.client.get("/").text
        self.assertEqual(len(re.findall(r'<input\b[^>]*\btype="file"', page)), 1)
        self.assertNotIn('team3-form', page)
        for text in ["Run both reviews", "teamAOutput", "teamBOutput", "teamADownloads", "teamBDownloads"]:
            self.assertIn(text, page)


if __name__ == "__main__":
    unittest.main()
