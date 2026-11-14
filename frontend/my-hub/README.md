# Orbital Health frontend

Next.js mission-control dashboard connected to the DRF API. The interface reads persisted telemetry, feature history and review alerts from the backend; it does not substitute hard-coded readings for the live data flow.

## Local end-to-end demo (Windows PowerShell)

Install dependencies once from the repository root:

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend\my-hub
npm ci
```

Start Django in one terminal:

```powershell
Set-Location D:\NASA\draft
.\backend\.venv\Scripts\python.exe backend\manage.py migrate
.\backend\.venv\Scripts\python.exe backend\manage.py setup_demo --username crew --password 'REPLACE-WITH-A-LOCAL-PASSWORD'
.\backend\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

Run the simulator/analysis/persistence pipeline in a second terminal:

```powershell
Set-Location D:\NASA\draft
.\backend\.venv\Scripts\python.exe backend\manage.py run_mission_simulator --profile-id crew-01 --scenario demo --interval 1 --seed 42
```

This command generates the same versioned 36-feature events as the analytics module, calibrates and runs the nonlinear detector, validates and stores each event, and creates review alerts for non-normal results. The `demo` sequence includes baseline, nonlinear interaction, sensor artifact, gradual drift, signal-loss and radiation scenarios. Use `--scenario normal` for a stable baseline, `--max-events 10` for a finite run, or Ctrl+C to stop.

Start the web app in a third terminal:

```powershell
Set-Location D:\NASA\draft\frontend\my-hub
npm run dev
```

Replace the example password before running `setup_demo`; it is not a built-in credential. If `crew` already exists with another password, reset it with `.\backend\.venv\Scripts\python.exe backend\manage.py changepassword crew`. Open [http://localhost:3000](http://localhost:3000), sign in with the username/password for that backend database, and select the generated crew profile. The API token is held in the current browser session and is removed when signing out. The dashboard refreshes its persisted backend data every five seconds.

## Mission workspaces

The **Mission brief** is the starting point: it summarizes the latest analysis, data quality, available profile history, and open review count before showing links to the tools. **Signals** contains measurements, profile references, trends, and the full indicator explorer; **Reviews** contains alert evidence and review actions; **Timeline** contains recorded telemetry events; **Reports** generates an AI-assisted review of a clearly labeled synthetic scenario. Reports do not analyze the selected profile's saved telemetry. Model-generated observations are exploratory and are not medical diagnoses.

## API connection

The app defaults to `http://127.0.0.1:8000`. To use another backend, set `NEXT_PUBLIC_API_BASE_URL` in `.env.local` before starting Next.js:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

The backend's `CORS_ALLOWED_ORIGINS` must include the exact browser origin. See [`../../../backend/README.md`](../../../backend/README.md) for all endpoints, response shapes, auth rules and constraints, or open Swagger at `/api/docs/`.

The profile report is fetched from `GET /api/v1/profiles/{profile_id}/insights/?limit=120`. It provides catalog metrics, per-profile robust references, recent history, evidence, and suggested checks. Per-feature XGBoost forecasters use at least 36 good-quality observations to predict one next sample from the feature's own lagged history plus available mission context; the API also reports walk-forward median absolute error. These are exploratory profile-specific estimates, not clinical forecasts or evidence of improved accuracy. Trend reports refresh every 30 seconds; mission state and review lists refresh every five seconds. The chart distinguishes observed samples, the prior profile median, and the next-sample estimate.

## Health Copilot

The **Health Copilot** route (`/chat`) lives in the same Next.js application and reuses the signed-in mission API session and selected crew profile. Its evidence-linked chat layout is informed by Open WebUI's conversation patterns, but is implemented as native Next.js UI and does not bundle Open WebUI source or require a second browser app.

Start the local Gemini adapter from the repository root in another terminal:

```bash
export GEMINI_API_KEY="your-google-ai-studio-key"
export MISSION_API_BASE_URL="http://127.0.0.1:8000"
python -m chatbot.server
```

In the Next.js terminal, set `CHATBOT_API_URL=http://127.0.0.1:8766` in `.env.local` (see [`env.example`](./env.example)) and run `npm run dev`. Sign in to mission control, select a synthetic crew profile, and open **Health copilot** in the sidebar. The browser sends the existing session token to a same-origin Next.js route; that route proxies to the local chatbot service, which retrieves the authorized dashboard and profile report and keeps the Gemini key server-side.

The copilot requires explicit confirmation before sending synthetic profile context and the question to Google AI Studio. Real telemetry is rejected by the chatbot service. Conversations remain in memory for the current page session only. See [`../../../chatbot/README.md`](../../../chatbot/README.md) for safety boundaries and the adapter contract.

## Daily Reports

The **Reports** workspace connects to the separate FastAPI report service. Install its dependencies with `python -m pip install -r report/requirements.txt`, configure `report/.env` from `report/.env.example`, and start it from the repository root with `python -m report.server`. Set `REPORT_API_URL=http://127.0.0.1:8001` in this frontend's `.env.local` and restart Next.js.

The report service generates a new randomized synthetic dataset for each selected scenario; it does not analyze the current profile's saved telemetry. The frontend requires explicit consent before a generated dataset and scenario context are sent to Google AI Studio. The proxy checks access to the selected profile, while crew name and profile ID are excluded from the Gemini prompt. Reports are not persisted. See [`../../../report/README.md`](../../../report/README.md) for setup, API endpoints, model configuration, and limitations.

## Frontend checks

```powershell
npm run lint
npx tsc --noEmit
npm run build
```

The chart uses the series endpoint and renders missing samples as gaps (not normal/zero values). Analysis scores are empirical ranks, not probabilities, and all demo data is visibly synthetic and not clinically validated.
