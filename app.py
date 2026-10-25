"""Compare pod v0.3.0 services and offer review ZIP downloads."""
import asyncio
from base64 import b64decode
from io import BytesIO
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
from urllib.parse import quote
from uuid import uuid4
from zipfile import ZipFile, ZIP_STORED

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from contract import load_contract, validate_payload

ROOT = Path(__file__).resolve().parent
SPEC = load_contract(ROOT / "shared-openapi.yaml")
TEAM3_API_URL = os.getenv("TEAM3_API_URL", "http://127.0.0.1:8001")
app = FastAPI(title="Cross-Team PDF Comparison Interface", version="0.3.0", description="Client of the shared pod v0.3.0 contract. Runs setup, catalog/health checks, one uploaded-file request, and coverage lookup; this is not a complete acceptance test suite.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "static/index.html", headers={"Cache-Control": "no-store"})


@app.get("/app.js", include_in_schema=False)
def script():
    return FileResponse(ROOT / "static/app.js", headers={"Cache-Control": "no-store"})


def response_errors(response, schema):
    try:
        payload = response.json()
    except ValueError:
        return None, ["Response is not JSON"]
    return payload, validate_payload(SPEC, schema, payload)


def input_errors(payload, filename, content):
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        return []
    expected = {"file_name": filename, "sha256": sha256(content).hexdigest(), "size_bytes": len(content)}
    errors = []
    if any(payload.get("input", {}).get(key) != value for key, value in expected.items()):
        errors.append("input metadata does not match the uploaded file")
    output = payload.get("output_pdf", {})
    if output.get("modified") is False:
        try:
            if b64decode(output["content_base64"], validate=True) != content:
                errors.append("output_pdf is marked unmodified but differs from the upload")
        except (ValueError, KeyError):
            errors.append("Invalid unmodified output PDF")
    return errors


async def call_team(label, base_url, filename, content, content_type):
    base = base_url.strip().rstrip("/")
    session = str(uuid4())
    result = {"label": label, "session_id": session, "success": False, "status_code": 0, "body": None, "error": None, "source": "system", "contract_valid": False, "contract_errors": [], "health": None, "checks": None, "coverage": None}
    if not base:
        result.update(error="URL is required", source="tester")
        return result
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            setup = await client.post(base + "/test/setup", json={"session_id": session, "setup": {}}, timeout=10.0)
            payload, errors = response_errors(setup, "SessionRef" if setup.status_code == 201 else "TestError")
            if setup.status_code != 201 or errors or payload.get("session_id") != session:
                result.update(status_code=setup.status_code, error="Test-session setup failed; processing was not run.", contract_errors=errors, setup=payload)
                return result
            preflight_errors = []
            for path, key, schema in [("/health", "health", "Health"), ("/checks", "checks", "CheckList")]:
                response = await client.get(base + path)
                payload, errors = response_errors(response, schema)
                result[key] = payload
                preflight_errors.extend([f"{path}: {error}" for error in errors])
                if response.status_code != 200:
                    preflight_errors.append(f"{path}: expected HTTP 200, got {response.status_code}")
                if path == "/health" and isinstance(payload, dict) and payload.get("spec_version") != "0.3.0":
                    preflight_errors.append("/health: spec_version must be 0.3.0")
            response = await client.post(base + "/process", headers={"Accept": "application/json"}, data={"session_id": session}, files={"file": (filename, content, content_type)})
            schema = "EvaluationResult" if response.status_code == 200 else "Error"
            payload, errors = response_errors(response, schema)
            if not errors:
                errors.extend(input_errors(payload, filename, content))
            if response.status_code not in {200, 400, 413, 415, 422, 500, 503}:
                errors.append(f"Unexpected process HTTP status {response.status_code}")
            report = await client.get(base + "/test/report", params={"session_id": session})
            coverage, coverage_errors = response_errors(report, "SystemReport" if report.status_code == 200 else "TestError")
            if report.status_code != 200 or not isinstance(coverage, dict) or coverage.get("session_id") != session:
                coverage_errors.append("Expected this session's coverage report with HTTP 200")
            all_errors = preflight_errors + errors + [f"/test/report: {error}" for error in coverage_errors]
            result.update(status_code=response.status_code, body=payload, coverage=coverage, contract_errors=all_errors, contract_valid=not all_errors,
                          success=response.status_code == 200 and not all_errors,
                          error="; ".join(all_errors) if all_errors else (None if response.status_code == 200 else payload.get("message", "Processing failed")))
            if response.status_code == 503:
                result["source"] = "communication"
                result["outcome"] = "error"
            return result
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        result.update(error=f"Connection failed: {exc}", source="communication", outcome="error")
        return result


@app.post("/api/compare")
async def compare_teams(file: UploadFile = File(...), team_a_url: str = Form(...), team_b_url: str = Form(...)) -> dict:
    if not file.filename:
        raise HTTPException(400, "A file is required.")
    content = await file.read()
    await file.close()
    a, b = await asyncio.gather(call_team("Team A", team_a_url, file.filename, content, file.content_type or "application/octet-stream"), call_team("Team B", team_b_url, file.filename, content, file.content_type or "application/octet-stream"))
    return {"team_a": a, "team_b": b}


@app.post("/api/team3/process", response_class=Response)
async def process_with_team3(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(400, "A file is required.")
    filename = file.filename.replace("\\", "/").rsplit("/", 1)[-1]
    content = await file.read()
    await file.close()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(TEAM3_API_URL.rstrip("/") + "/process", headers={"Accept": "application/json"}, files={"file": (filename, content, file.content_type or "application/octet-stream")})
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise HTTPException(502, f"Could not reach Team 3: {exc}") from exc
    payload, errors = response_errors(response, "EvaluationResult" if response.status_code == 200 else "Error")
    if not errors:
        errors.extend(input_errors(payload, filename, content))
    if errors:
        raise HTTPException(502, "Team 3 did not return the shared v0.3.0 JSON contract: " + "; ".join(errors))
    if response.status_code not in {200, 400, 413, 415, 422}:
        raise HTTPException(502, payload.get("message", "Team 3 processing failed."))
    archive = BytesIO()
    with ZipFile(archive, "w", compression=ZIP_STORED) as output:
        output.writestr("report.json", json.dumps(payload, indent=2).encode("utf-8"))
        output.writestr("original/report.json" if filename == "report.json" else filename, content)
        if payload["status"] == "completed":
            for key in ("output_pdf", "report_pdf"):
                name = payload[key]["file_name"].replace("\\", "/").rsplit("/", 1)[-1]
                if name in output.namelist():
                    name = "outputs/" + name
                output.writestr(name, b64decode(payload[key]["content_base64"], validate=True))
    stem = PurePosixPath(filename).stem
    return Response(archive.getvalue(), media_type="application/zip", headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(stem + '_review.zip', safe='')}"})
