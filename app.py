from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

app = FastAPI(
    title="Cross-Team PDF Comparison Interface",
    version="0.1.0",
    description=(
        "Minimal black-box evaluation platform for uploading a PDF to two separate "
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
        raise HTTPException(status_code=400, detail="A PDF file is required.")

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed.")

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
                    files={"file": (file.filename, content, "application/pdf")},
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
