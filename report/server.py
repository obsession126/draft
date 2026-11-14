"""
FastAPI-сервер для генерації щоденних звітів про здоров'я астронавтів.
Запускається окремо і надає REST API для фронтенду.

Запуск:
    python -m report.server
    або
    uvicorn report.server:app --host 0.0.0.0 --port 8001 --reload
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Додаємо root проєкту в sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from report.ai_report_generator import generate_daily_report

app = FastAPI(
    title="Orbital Health — Daily Report API",
    description="AI-powered daily health reports for astronaut monitoring.",
    version="1.0.0",
)

# CORS — дозволяємо фронтенд
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────
#  Request / Response models
# ──────────────────────────────────────────────────────────

class ReportRequest(BaseModel):
    astronaut_name: str = "Crew Member 01"
    profile_id: str = "crew-01"
    mission_name: str = "Demo Mission"
    mission_day: Optional[int] = None
    mission_phase: str = "transit"
    scenario: str = "normal"


class HealthResponse(BaseModel):
    status: str
    version: str


# ──────────────────────────────────────────────────────────
#  Endpoints
# ──────────────────────────────────────────────────────────

@app.get("/api/report/health/", response_model=HealthResponse)
async def health_check():
    """Перевірка стану API."""
    return {"status": "ok", "version": "1.0.0"}


@app.post("/api/report/generate/")
async def generate_report(request: ReportRequest):
    """
    Генерація щоденного звіту про здоров'я астронавта.
    Використовує симульовані дані та Gemini AI для аналізу.
    """
    try:
        report = generate_daily_report(
            astronaut_name=request.astronaut_name,
            profile_id=request.profile_id,
            mission_name=request.mission_name,
            mission_day=request.mission_day,
            mission_phase=request.mission_phase,
            scenario=request.scenario,
        )
        return report
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")


@app.get("/api/report/generate/")
async def generate_report_get(
    astronaut_name: str = Query("Crew Member 01"),
    profile_id: str = Query("crew-01"),
    mission_name: str = Query("Demo Mission"),
    mission_day: Optional[int] = Query(None),
    mission_phase: str = Query("transit"),
    scenario: str = Query("normal"),
):
    """
    GET-варіант генерації звіту (для простого тестування).
    """
    try:
        report = generate_daily_report(
            astronaut_name=astronaut_name,
            profile_id=profile_id,
            mission_name=mission_name,
            mission_day=mission_day,
            mission_phase=mission_phase,
            scenario=scenario,
        )
        return report
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")


@app.get("/api/report/scenarios/")
async def list_scenarios():
    """Список доступних сценаріїв симуляції."""
    return {
        "scenarios": [
            {"id": "normal", "label": "Normal Conditions", "description": "Стандартні умови польоту"},
            {"id": "stress", "label": "High Stress", "description": "Підвищений рівень стресу"},
            {"id": "fatigue", "label": "Fatigue", "description": "Втома та порушення сну"},
            {"id": "radiation_event", "label": "Radiation Event", "description": "Радіаційна подія"},
        ]
    }


# ──────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("REPORT_PORT", "8001"))
    uvicorn.run("report.server:app", host="0.0.0.0", port=port, reload=True)
