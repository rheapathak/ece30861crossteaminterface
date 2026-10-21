# Cross-Team File Comparison Interface

This project is a minimal black-box prototype for comparing two teams' file-processing APIs without exposing either team's internal code.

## What this platform does

- Upload any file from the browser
- Send that file to a configurable Team A endpoint
- Send the same file to a configurable Team B endpoint
- Show both responses in one place
- Handle unreachable, invalid, or failed endpoints gracefully

This is intentionally a black-box testing setup. The platform does not inspect, import, or reverse-engineer either team’s implementation. It only calls over HTTP and reads the returned JSON.

## What each team needs to do on their end

Each team must deploy a network-accessible service that follows the same external contract. The platform will interact with the service as a client, not by reading code or using internal libraries.

### 1. Deploy a public or private service
Each team needs to host a web service that is reachable by the testing platform. It can be deployed in any language or stack, including Python, Java, C#, Node.js, or a cloud-hosted service. The implementation details are not standardized.

Examples of valid deployment targets:

- A Docker container on a cloud VM
- A containerized API in AWS, Azure, or GCP
- A local development server during testing
- A production deployment with authentication and HTTPS

### 2. Expose the required health endpoint
Each team should provide:

- `GET /health`

Example response:

```json
{
  "status": "healthy"
}
```

This lets the platform confirm the service is up before sending documents.

### 3. Expose the processing endpoint
Each team should provide:

- `POST /process`
- Accept `multipart/form-data`
- Expect a file under the field name `file`

Example request:

```bash
curl -X POST \
  -F "file=@example.txt" \
  https://team-a.example.com/process
```

This is the key black-box interface. The platform accepts files of any type and forwards the file's name and content type. Each team service is responsible for deciding which file types it can process; the platform does not validate file extensions.

### 4. Return a consistent JSON response
Each team must return JSON in the same shape so the platform can compare outputs reliably.

Example response:

```json
{
  "status": "success",
  "results": [
    {
      "field": "invoice_number",
      "value": "INV-12345",
      "confidence": 0.98
    },
    {
      "field": "customer_name",
      "value": "John Smith",
      "confidence": 0.95
    }
  ],
  "processing_time_ms": 1200
}
```

Recommended response rules:

- `status` should be either `success` or `error`
- `results` should be a list of extracted values
- `processing_time_ms` is optional but useful for debugging and comparison
- `confidence` should be numeric between 0 and 1 when present

### 5. Use clear error handling
If the uploaded file is invalid or the processing fails, the service should return an HTTP error code and a JSON message when possible.

Examples:

- `400 Bad Request` for malformed or unsupported files
- `401 Unauthorized` for missing or invalid authentication
- `500 Internal Server Error` for internal processing issues

Example error response:

```json
{
  "status": "error",
  "message": "Invalid file upload"
}
```

### 6. Keep the service stateless unless you explicitly need state
If the service does not depend on prior requests, it should remain stateless. In that case, no reset endpoint is required.

If state matters, a team may optionally implement:

- `POST /reset`

Example:

```json
{
  "status": "reset"
}
```

The testing platform can call `/reset` before a batch of tests if repeatability is required.

### 7. Authentication is allowed but must be agreed upon
Each team may require authentication, such as an API key or bearer token. The platform should store that configuration separately per team.

Example header:

```http
Authorization: Bearer <TEAM_API_KEY>
```

The open contract should document the required auth mechanism, but the platform itself should not need to know the team’s internal implementation details.

### 8. No code-sharing is required
The testing platform and the teams do not need to share code. They only need to agree on the service contract and communicate over the network.

This is the essential principle behind the assignment: each team can implement the same observable interface in its own way without exposing internal logic.

## Minimal example team implementation

Here is a tiny FastAPI example of what a team service could look like:

```python
from fastapi import FastAPI, File, UploadFile

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.post("/process")
async def process(file: UploadFile = File(...)):
    return {
        "status": "success",
        "results": [
            {"field": "invoice_number", "value": "INV-12345", "confidence": 0.98}
        ],
        "processing_time_ms": 1200,
    }
```

This is only an example. The actual implementation may differ completely, but the external HTTP behavior should match the same contract.

## Required contract summary

The platform expects the following contract from each team:

- `GET /health` -> returns healthy status
- `POST /process` -> accepts a file in a multipart upload
- Response body is JSON and follows the same schema
- HTTP status codes are used consistently for success and failure
- The service is reachable over the network
- No source code access is required to evaluate the system

The exact OpenAPI contract is in `openapi.yaml`.

## Run this platform locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

Then open:

- http://localhost:8000

## How to use the platform

1. Enter the base URL for Team A, for example `https://team-a.example.com`
2. Enter the base URL for Team B, for example `https://team-b.example.com`
3. Upload a file of any type
4. Click "Run comparison"
5. Review the returned JSON for each team

## Team 3 file pass-through

The page also has a dedicated Team 3 pass-through form. It sends the selected
file to `POST /process` on the Team 3 service and offers the returned file for
download. The current Team 3 endpoint is intentionally a no-op: it returns
the uploaded file bytes unchanged.

Start the Team 3 service separately on port 8001 from its project directory:

```bash
cd ../team-3-project
uvicorn app:app --host 0.0.0.0 --port 8001
```

The interface uses `http://127.0.0.1:8001` by default; set `TEAM3_API_URL`
before starting the interface to point to a different Team 3 service. This
pass-through flow is separate from the JSON comparison flow above, so it does
not require or invoke the other team's endpoint.

## Important note

This project is intentionally simple. It does not inspect either team's source code. It only communicates over HTTP, which is the correct pattern for a black-box cross-team interface.
