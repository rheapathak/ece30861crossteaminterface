from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_compare_teams_accepts_non_pdf_and_preserves_content_type() -> None:
    responses = [
        httpx.Response(
            200,
            json={"status": "success"},
            request=httpx.Request("POST", f"http://team-{team}.example.com/process"),
        )
        for team in ("a", "b")
    ]

    with patch(
        "app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        side_effect=responses,
    ) as post:
        response = client.post(
            "/api/compare",
            data={
                "team_a_url": "http://team-a.example.com",
                "team_b_url": "http://team-b.example.com",
            },
            files={"file": ("sample.txt", b"plain text", "text/plain")},
        )

    assert response.status_code == 200
    assert response.json()["team_a"]["success"] is True
    assert response.json()["team_b"]["success"] is True
    assert post.await_count == 2
    for call in post.await_args_list:
        assert call.kwargs["files"]["file"] == (
            "sample.txt",
            b"plain text",
            "text/plain",
        )


def test_team3_proxy_returns_output_file() -> None:
    pdf_bytes = b"%PDF-1.4\nplaceholder PDF bytes\n"
    upstream_response = httpx.Response(
        200,
        content=pdf_bytes,
        headers={"content-type": "application/pdf"},
        request=httpx.Request("POST", "http://127.0.0.1:8001/process"),
    )

    with patch(
        "app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=upstream_response,
    ) as post:
        response = client.post(
            "/api/team3/process",
            files={"file": ("sample.pdf", pdf_bytes, "application/pdf")},
        )

    assert response.status_code == 200
    assert response.content == pdf_bytes
    assert response.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''sample.pdf" in response.headers["content-disposition"]
    assert post.await_count == 1


def test_team3_proxy_accepts_non_pdf_and_preserves_content_type() -> None:
    response_bytes = b"processed text file"
    upstream_response = httpx.Response(
        200,
        content=response_bytes,
        headers={"content-type": "text/plain"},
        request=httpx.Request("POST", "http://127.0.0.1:8001/process"),
    )
    with patch(
        "app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=upstream_response,
    ) as post:
        response = client.post(
            "/api/team3/process",
            files={"file": ("sample.txt", b"plain text", "text/plain")},
        )

    assert response.status_code == 200
    assert response.content == response_bytes
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert "filename*=UTF-8''sample.txt" in response.headers["content-disposition"]
    forwarded_file = post.await_args.kwargs["files"]["file"]
    assert forwarded_file == ("sample.txt", b"plain text", "text/plain")


def test_team3_proxy_reports_upstream_failure() -> None:
    upstream_response = httpx.Response(
        503,
        text="service unavailable",
        request=httpx.Request("POST", "http://127.0.0.1:8001/process"),
    )

    with patch(
        "app.httpx.AsyncClient.post",
        new_callable=AsyncMock,
        return_value=upstream_response,
    ):
        response = client.post(
            "/api/team3/process",
            files={"file": ("sample.pdf", b"%PDF", "application/pdf")},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "service unavailable"}
