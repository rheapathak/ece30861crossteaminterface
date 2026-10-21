from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

TEAM3_API_URL = os.getenv("TEAM3_API_URL", "http://127.0.0.1:8001")

app = FastAPI(
    title="Cross-Team File Comparison Interface",
    version="0.1.0",
    description=(
        "Minimal black-box evaluation platform for uploading a file to two separate "
        "team APIs and comparing their outputs."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/")
def read_index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/app.js")
def read_app_js() -> FileResponse:
    return FileResponse("static/app.js")


@app.post("/api/compare")
async def compare_teams(
    file: UploadFile = File(...),
    team_a_url: str = Form(...),
    team_b_url: str = Form(...),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A file is required.")

    content = await file.read()

    async def call_team(label: str, base_url: str) -> dict[str, Any]:
        cleaned = base_url.strip()
        if not cleaned:
            return {
                "label": label,
                "success": False,
                "status_code": 0,
                "error": "URL is required",
            }

        try:
            url = f"{cleaned.rstrip('/')}/process"
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    url,
                    files={
                        "file": (
                            file.filename,
                            content,
                            file.content_type or "application/octet-stream",
                        )
                    },
                )
            try:
                payload = response.json()
            except ValueError:
                payload = {"raw_text": response.text}

            return {
                "label": label,
                "success": response.is_success,
                "status_code": response.status_code,
                "body": payload,
                "error": None if response.is_success else (payload.get("detail") or payload.get("message") or "Request failed"),
            }
        except httpx.HTTPError as exc:
            return {
                "label": label,
                "success": False,
                "status_code": 0,
                "body": None,
                "error": f"Connection failed: {str(exc)}",
            }

    result_a, result_b = await asyncio.gather(
        call_team("Team A", team_a_url),
        call_team("Team B", team_b_url),
    )

    return {
        "team_a": result_a,
        "team_b": result_b,
    }


@app.post("/api/team3/process", response_class=Response)
async def process_with_team3(file: UploadFile = File(...)) -> Response:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A file is required.")

    filename = file.filename.rsplit("/", maxsplit=1)[-1].rsplit("\\", maxsplit=1)[-1]

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{TEAM3_API_URL.rstrip('/')}/process",
                files={
                    "file": (
                        filename,
                        content,
                        file.content_type or "application/octet-stream",
                    )
                },
            )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach the Team 3 processing service: {exc}",
        ) from exc

    if not response.is_success:
        status_code = response.status_code if 400 <= response.status_code < 500 else 502
        try:
            error_body = response.json()
        except ValueError:
            error_body = response.text
        if isinstance(error_body, dict):
            detail = error_body.get("detail") or error_body.get("message")
        else:
            detail = error_body
        raise HTTPException(
            status_code=status_code,
            detail=detail or f"Team 3 processing failed with status {response.status_code}.",
        )

    return Response(
        content=response.content,
        media_type=response.headers.get(
            "content-type", file.content_type or "application/octet-stream"
        ),
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
