# Daily scenario report service

This local FastAPI service generates a structured report for a freshly randomized
synthetic scenario. It does **not** analyze the selected profile's stored dashboard
telemetry. Scenario reference bands and review flags are illustrative demo logic, not
validated space-medicine thresholds, clinical triage, or a diagnosis.

## Setup

From the repository root:

```bash
python -m pip install -r report/requirements.txt
cp report/.env.example report/.env
```

Set a newly created Google AI Studio key in `report/.env`. The report service defaults
to `gemini-3.5-flash-lite`; set `GEMINI_MODEL` to another Flash model available to
your account if needed. Shell environment variables take precedence over values in
`report/.env`. Never commit `.env` or paste an API key into source code.

Start the service in its own terminal:

```bash
python -m report.server
```

It listens on `127.0.0.1:8001` by default. In
`frontend/my-hub/.env.local`, configure:

```dotenv
REPORT_API_URL=http://127.0.0.1:8001
```

Restart Next.js after changing environment variables. The Reports workspace uses a
same-origin Next.js proxy, checks that the signed-in user can access the selected
profile, and asks for explicit consent before sending a generated synthetic dataset
to Google AI Studio. Crew name and profile ID are not included in the Gemini prompt.
Real telemetry is not submitted to this report service.

## API

- `GET /api/report/health/` — service status and version.
- `GET /api/report/scenarios/` — supported synthetic scenarios.
- `POST /api/report/generate/` — generate a structured report.
- `GET /api/report/generate/` — equivalent query-parameter form for local testing.

The `normal`, `stress`, `fatigue`, and `radiation_event` scenarios each produce new
randomized measurements and a previous-sample comparison. The report includes the
generated readings, AI narrative, deterministic comparison notes, model name, and a
synthetic-data disclaimer. Generated reports are held in frontend memory only; the
service does not persist them.

Interactive API documentation is available at `http://127.0.0.1:8001/docs`.

## Troubleshooting

`gemini_configured: true` confirms that a non-empty key was loaded; it does not
validate the key with Google. If generation fails, check the Report service
terminal for the sanitized provider error. The log redacts the API key. Restart
the service after changing `.env`.
