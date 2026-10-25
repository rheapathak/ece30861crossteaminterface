# Cross-team PDF interface

Client for the shared pod API v0.3.0. `shared-openapi.yaml` is the system contract
both teams implement; `openapi.yaml` documents this interface's own routes.

Start each team's service separately. Then, from this directory:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8000. Enter each team's base URL without /process or /docs.
For a local connectivity check, use http://127.0.0.1:8001 for both teams.
This is one uploaded-file comparison and contract check, not a complete course
acceptance suite and not an accessibility certification.

## Comparison flow

POST /api/compare accepts file, team_a_url and team_b_url. The interface creates
a unique session for each target with POST /test/setup (10-second timeout),
checks /health and /checks, sends the file and session_id to /process, then reads
/test/report. Project calls allow 60 seconds and are never retried. Setup failure
prevents project calls. Communication failures are labeled source: communication.
The filename and content type are preserved, including invalid and empty files.

Responses are validated against shared schema definitions. Returned PDF Base64
and SHA-256 are checked. `contract_valid` is separate from `success`: a correctly
formatted 415 error is contract-valid but indicates the file was rejected.
The screen omits long Base64 strings and provides JSON and PDF downloads.
Null coverage means instrumentation is unavailable, not zero coverage.

## Team 3 ZIP download

POST /api/team3/process calls Team 3's standard JSON API, then packages that JSON,
the original upload and (on completion) its output/report PDFs into a ZIP. Invalid
uploads get only JSON and the original. The interface does not perform PDF checks
or repairs. TEAM3_API_URL defaults to http://127.0.0.1:8001; set the environment
variable before starting to target a hosted Team 3 service. The two-team comparison
uses the URLs entered into the form independently of this environment variable.

## Tests and docs

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

The interface's own API explorer is at /docs and generated schema at /openapi.json.
Restart after changes; deployed services require a new deployment.
