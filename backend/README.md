# DRF backend

The backend persists telemetry from the synthetic analytics module and exposes a versioned API for the Next.js client. Analytics events use the single canonical contract in [`../analytics/event.schema.json`](../analytics/event.schema.json); the API validates incoming events against that file rather than maintaining a second schema.

This is a hackathon/demo backend, not a medical device or production deployment. Telemetry and anomaly labels are synthetic and must not be used for clinical decisions.

On macOS, the XGBoost wheel also requires an OpenMP runtime. Install it once with `brew install libomp` before starting Django. Linux/Windows deployments need the matching native runtime for their platform if XGBoost reports that OpenMP cannot be loaded.

## Local setup (Windows PowerShell)

Run these commands from the repository root:

```powershell
py -m venv backend\.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\backend\.venv\Scripts\python.exe backend\manage.py migrate
.\backend\.venv\Scripts\python.exe backend\manage.py setup_demo --username crew --password 'REPLACE-WITH-A-LOCAL-PASSWORD'
.\backend\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

Replace the example password with one you choose; it is not a built-in credential. `setup_demo` creates a local account and its `crew-01` profile without shipping a default password or exposing an API token. Use the same username/password in the frontend. If the account already exists, `setup_demo` verifies the supplied password and will not reset it. To change an existing user's password, run `.\backend\.venv\Scripts\python.exe backend\manage.py changepassword crew` and enter a new password when prompted. To create a regular user instead, use `createsuperuser` and create the profile through the authenticated API.

By default, the local backend uses SQLite at `backend\db.sqlite3`, permits the local Next.js origins `http://localhost:3000` and `http://127.0.0.1:3000`, and runs with Django debug enabled. Configuration can be overridden with environment variables:

| Variable | Purpose |
|---|---|
| `DJANGO_DEBUG` | Set to `false` outside local development. |
| `DJANGO_SECRET_KEY` | Required when debug is disabled. Supply a private, randomly generated value. |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated Django hosts; defaults to `localhost,127.0.0.1,testserver`. |
| `CORS_ALLOWED_ORIGINS` | Comma-separated browser origins; defaults to the two local Next.js origins. |
| `DJANGO_DATABASE_PATH` | SQLite database file path. |

Migrations and tests:

```powershell
.\backend\.venv\Scripts\python.exe backend\manage.py check
.\backend\.venv\Scripts\python.exe backend\manage.py makemigrations --check --dry-run
.\backend\.venv\Scripts\python.exe backend\manage.py test api.tests -v 2
```

## Authentication and profiles

Private endpoints require a Django REST Framework token:

```powershell
$login = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/auth/token/ `
  -ContentType 'application/json' `
  -Body '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}'
$headers = @{ Authorization = "Token $($login.token)" }
```

Create a profile for the authenticated user. Profile IDs are URL-safe and unique:

```powershell
$profile = @{
  profile_id = 'crew-01'
  display_name = 'Crew Member 01'
  mission_name = 'Demo mission'
  mission_phase = 'transit'
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/profiles/ `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $profile
```

Authenticated users can only list and access their own profiles and telemetry; staff users can access all profiles. Use the `Authorization: Token <key>` header (not `Bearer`). Do not place tokens in URLs or browser storage that is readable by untrusted scripts.

## Full synthetic sensor and analysis pipeline

Run this in a separate terminal after the backend server and demo profile are ready:

```powershell
.\backend\venv\Scripts\python.exe backend\manage.py run_mission_simulator --profile-id crew-01 --scenario demo --interval 1 --seed 42
```

This runs the analytics simulator and nonlinear detector, then validates and persists each event and any associated alert through the backend's normal ingestion service. The simulation includes normal, nonlinear interaction, sensor artifact, gradual drift, signal-loss and radiation-event scenarios. Use `--scenario normal`, `--max-events 10`, or Ctrl+C to control the run. The same validated contract, database, API permissions, alert lifecycle and frontend are used as they would be for events from a hardware adapter; only the measurement source is simulated.

`bridge_analytics` remains available for running the analytics HTTP/SSE service as a separate process and forwarding its events over the authenticated DRF API. It is not required for the standard local demo flow.

### Minute aggregation and raw-data retention

Run the following command at least once per minute using a local scheduler. On macOS, use `backend/.venv/bin/python backend/manage.py compact_telemetry` instead of the PowerShell path below.

```powershell
.\backend\.venv\Scripts\python.exe backend\manage.py compact_telemetry
```

It rolls completed minutes into per-profile summaries (good-value mean/min/max, quality counts, category counts, and mission-context summaries). Raw measurement payloads are retained for seven days from `measured_at`, then redacted only after aggregation has succeeded; a digest and small event metadata remain to preserve idempotency. Events linked to alerts are aggregated for trend analysis but their original payloads and alert evidence are preserved. The command is safe to rerun; it only processes unaggregated events. Scheduling is not bundled into the demo server, so without the scheduled command neither compaction nor raw-payload retention is enforced.

## API contract

All JSON timestamps are ISO-8601 with timezone information. Analytics payloads preserve their original `schema_version`, 36-feature `feature_names` and `feature_vector`, named `measurements`, mission `context`, and `analysis` result. Ingest rejects events that fail the shared JSON Schema or whose vector does not match `measurements[name].value`.

| Method and path | Authentication | Purpose |
|---|---|---|
| `GET /api/v1/health/` | Public | Liveness and telemetry schema version. |
| `POST /api/v1/auth/token/` | Public | Obtain a DRF token with username/password. |
| `GET, POST /api/v1/profiles/` | Token | List owned profiles or create one. |
| `GET /api/v1/profiles/{profile_id}/` | Token | Read an owned profile. |
| `GET /api/v1/profiles/{profile_id}/dashboard/` | Token | Latest event, open alerts, count, and sync freshness. |
| `GET /api/v1/profiles/{profile_id}/insights/?limit=120` | Token | Profile report: recent event summary, all 36 feature histories and robust personal-baseline comparisons, plus evidence-linked insights. `limit` is 1–500. |
| `GET /api/v1/profiles/{profile_id}/series/?feature=hr_bpm` | Token | Ordered values for one catalog feature. Supports `since`, `until`, and `limit` (1–500). |
| `GET /api/v1/metadata/parameters/` | Token | Canonical feature names, labels, units, and categories. |
| `POST /api/v1/telemetry/ingest/` | Token | Ingest one event wrapped as `{"event": <canonical event>}`. Same event ID and payload returns `200`; changed content returns `409`. |
| `POST /api/v1/telemetry/sync/` | Token | Atomic offline batch, `{"events": [...]}`; up to 250 events. Optional `Idempotency-Key` supports safe batch replay. |
| `GET /api/v1/telemetry/events/` | Token | Paginated event history. Optional filters: `profile_id`, `status`, `scenario`, `since`, `until`; ordering by `measured_at`, `received_at`, or `anomaly_score`. |
| `GET /api/v1/telemetry/events/{event_id}/` | Token | Read an event visible to the authenticated user. |
| `GET /api/v1/telemetry/stream/?profile_id=crew-01` | Token | SSE stream of stored canonical events; supports `Last-Event-ID`. |
| `GET /api/v1/alerts/?profile_id=crew-01&status=open` | Token | Paginated alerts. |
| `POST /api/v1/alerts/{alert_id}/acknowledge/` | Token | Acknowledge an open alert. |
| `POST /api/v1/alerts/{alert_id}/resolve/` | Token | Resolve an alert. |
| `GET /api/schema/` | Public | OpenAPI schema. |
| `GET /api/docs/` | Public | Swagger UI. |

The SSE endpoint requires an Authorization header; native browser `EventSource` cannot set one. A browser client should use `fetch()` with the token header and read the response stream, or use an authenticated same-origin proxy. Do not weaken API authentication by putting the token in a query parameter.

The event-history endpoint returns full raw events still within the retention window and alert-linked evidence; archived payloads are omitted. The series and insights endpoints include minute aggregates so profile trends remain available after raw-payload redaction.

The ingest response includes `event_id`, `profile_id`, `created`, `duplicate`, `analysis_status`, `received_at`, and `schema_version`. Batch responses include `batch_id`, `event_ids`, `created_count`, `duplicate_count`, `created_at`, `schema_version`, and `idempotent_replay`. Alert states are `open`, `acknowledged`, and `resolved`.

The profile insights response includes `schema_version`, profile metadata, report window, summary, ordered `metrics`, and `insights`. Each metric includes its latest quality/value, personal reference statistics, status, up to 48 historical points, and a `trend_model` result. Older history points are one-minute aggregates; each reports its sample count and observed minimum/maximum. The XGBoost result reports model/version status, usable history count, forecast horizon/value, robust trend direction, selected mission-context features, and (for numeric channels) median absolute error on a chronological holdout. Forecasts are one sample ahead, require at least 36 good-quality observations, and are not medical predictions. An insight includes `code`, `severity`, `title`, `summary`, optional `interaction_summary`, evidence, recommended checks, contributing metric names, and model relationship labels. Frontend clients should treat this endpoint as the source for explanatory report content rather than reconstructing explanations from anomaly scores.

The personal comparison uses earlier normal, good-quality raw samples and minute-aggregate means (median and median absolute deviation); aggregate buckets enter the baseline only when all their events had a normal event-level status. It is an exploratory change indicator, not a medical threshold. The detector's empirical tail rank is not a probability. Model feature contributions identify patterns the model used, not causal relationships. Synthetic values and scenario labels must remain visibly identified as synthetic.

## Demo limitations

- SQLite is suitable for the local demo, not concurrent high-volume production ingestion.
- DRF token authentication provides a simple integration boundary; production deployment needs a deliberate identity, token rotation, TLS, backups, retention, and operational monitoring plan.
- Analysis results express deviations from a synthetic baseline only; they are not medical diagnoses or validated recommendations.
- Raw events are stored with their full payload in SQLite until the scheduled compaction command runs. The agreed demo policy stores per-minute trend aggregates, retains unlinked raw event payloads for seven days, and preserves alert-linked raw evidence. Configure and monitor the scheduler before sustained ingestion; without it neither compaction nor raw-payload redaction occurs.
- Profile XGBoost estimators are fitted when the insights endpoint computes a report; the final chronological portion is held out for error estimation, and the same fitted estimator forecasts one sample ahead. Runtime and error metrics have not been benchmarked on real mission data.
- The standalone analytics HTTP service keeps a bounded in-memory history; the integrated mission simulator persists events directly to the backend database.
