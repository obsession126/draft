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
.\backend\.venv\Scripts\python.exe backend\manage.py setup_demo --username crew --password 'Choose-a-local-demo-password'
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

Open [http://localhost:3000](http://localhost:3000), sign in with the username/password passed to `setup_demo`, and select the generated crew profile. The API token is held in the current browser session and is removed when signing out. The dashboard refreshes its persisted backend data every five seconds.

## API connection

The app defaults to `http://127.0.0.1:8000`. To use another backend, set `NEXT_PUBLIC_API_BASE_URL` in `.env.local` before starting Next.js:

```dotenv
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

The backend's `CORS_ALLOWED_ORIGINS` must include the exact browser origin. See [`../../../backend/README.md`](../../../backend/README.md) for all endpoints, response shapes, auth rules and constraints, or open Swagger at `/api/docs/`.

## Frontend checks

```powershell
npm run lint
npx tsc --noEmit
npm run build
```

The chart uses the series endpoint and renders missing samples as gaps (not normal/zero values). Analysis scores are empirical ranks, not probabilities, and all demo data is visibly synthetic and not clinically validated.
