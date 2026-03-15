# Google Cloud Hosting (Cloud Run + Firestore)

This project includes an optional Google Cloud backend for hackathon compliance:

- **Cloud Run**: hosts backend API
- **Firestore (Native mode)**: stores sessions + events

## 1) Prerequisites

- `gcloud` installed and authenticated
- Billing-enabled GCP project
- Firestore location decided (default in script: `nam5`)

## 2) Deploy Backend (Secure by Default)

From project root:

```bash
pwsh ./scripts/deploy_cloud_run.ps1 -ProjectId <YOUR_GCP_PROJECT_ID> -Region us-central1 -ServiceName javpi-backend
```

Default deploy mode is **authenticated-only** (`--no-allow-unauthenticated`).

If you explicitly need public access (not recommended), pass:

```bash
pwsh ./scripts/deploy_cloud_run.ps1 -ProjectId <YOUR_GCP_PROJECT_ID> -AllowUnauthenticated -BackendApiKey <STRONG_SECRET>
```

The script:

1. Sets active project
2. Enables required APIs
3. Creates Firestore DB if missing
4. Deploys `backend/` to Cloud Run
5. Prints service URL

## 3) Configure Local Agent

Set these env vars in `.env` (or system env):

```env
GEMINI_API_KEY=...
JAVPI_BACKEND_URL=https://<your-cloud-run-url>
JAVPI_BACKEND_API_KEY=<optional-shared-secret>
JAVPI_BACKEND_TIMEOUT_SEC=1.5
JAVPI_FIRESTORE_COLLECTION=javpi_sessions
```

Notes:

- If `JAVPI_BACKEND_URL` is empty, desktop app runs normally with no cloud reporting.
- If backend sets `JAVPI_BACKEND_API_KEY`, client must send same key.

## 4) Backend API

- `GET /healthz`
- `POST /v1/sessions/start`
- `POST /v1/sessions/{session_id}/events`
- `POST /v1/sessions/{session_id}/end`
- `GET /v1/sessions/{session_id}`

## 5) Verify

- Run app locally (`python main.py` in your venv).
- Confirm session docs appear in Firestore collection `javpi_sessions`.
- Confirm `events` subcollection is populated.

## 6) Hardening Notes

- Keep Cloud Run authenticated-only for production.
- If using public mode, always set `JAVPI_BACKEND_API_KEY`.
- Telemetry payloads are sanitized/truncated in `CloudReporter` to avoid oversized writes.
