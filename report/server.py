"""FastAPI service for structured astronaut-health scenario reports."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from report.ai_report_generator import (
    ReportConfigurationError,
    ReportGenerationError,
    get_gemini_model,
    generate_daily_report,
)
from report.simulator_data import SCENARIOS


LOGGER = logging.getLogger("report")
Scenario = Literal["normal", "stress", "fatigue", "radiation_event"]

app = FastAPI(
    title="Orbital Health — Daily Report API",
    description="Structured AI summaries for synthetic astronaut-health scenarios.",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)


class ReportRequest(BaseModel):
    astronaut_name: str = Field(default="Crew Member 01", min_length=1, max_length=100)
    profile_id: str = Field(default="crew-01", min_length=1, max_length=128)
    mission_name: str = Field(default="Demo Mission", min_length=1, max_length=100)
    mission_day: int | None = Field(default=None, ge=1, le=3650)
    mission_phase: str = Field(default="transit", min_length=1, max_length=64)
    scenario: Scenario = "normal"


class HealthResponse(BaseModel):
    status: str
    version: str
    gemini_configured: bool
    model: str


def _generate(request: ReportRequest) -> dict:
    try:
        return generate_daily_report(
            astronaut_name=request.astronaut_name.strip(),
            profile_id=request.profile_id.strip(),
            mission_name=request.mission_name.strip(),
            mission_day=request.mission_day,
            mission_phase=request.mission_phase.strip(),
            scenario=request.scenario,
        )
    except ReportConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReportGenerationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        LOGGER.exception("Unexpected report generation failure.")
        raise HTTPException(
            status_code=500,
            detail="Report generation failed unexpectedly. Check the report service logs.",
        ) from exc


@app.get("/api/report/health/", response_model=HealthResponse)
async def health_check():
    gemini_configured = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    return {
        "status": "ok" if gemini_configured else "needs_configuration",
        "version": app.version,
        "gemini_configured": gemini_configured,
        "model": get_gemini_model(),
    }


@app.post("/api/report/generate/")
def generate_report(request: ReportRequest):
    return _generate(request)


@app.get("/api/report/generate/")
def generate_report_get(
    astronaut_name: str = Query("Crew Member 01", min_length=1, max_length=100),
    profile_id: str = Query("crew-01", min_length=1, max_length=128),
    mission_name: str = Query("Demo Mission", min_length=1, max_length=100),
    mission_day: int | None = Query(None, ge=1, le=3650),
    mission_phase: str = Query("transit", min_length=1, max_length=64),
    scenario: Scenario = Query("normal"),
):
    request = ReportRequest(
        astronaut_name=astronaut_name,
        profile_id=profile_id,
        mission_name=mission_name,
        mission_day=mission_day,
        mission_phase=mission_phase,
        scenario=scenario,
    )
    return _generate(request)


@app.get("/api/report/scenarios/")
async def list_scenarios():
    descriptions = {
        "normal": "Baseline-like synthetic readings with small random variation.",
        "stress": "Illustrative changes to selected cardiovascular and self-report signals.",
        "fatigue": "Illustrative changes to sleep, alertness, and stress signals.",
        "radiation_event": "Illustrative radiation-dose-rate scenario; not a dose limit.",
    }
    labels = {
        "normal": "Baseline scenario",
        "stress": "Elevated stress",
        "fatigue": "Fatigue",
        "radiation_event": "Radiation event",
    }
    return {
        "scenarios": [
            {"id": scenario, "label": labels[scenario], "description": descriptions[scenario]}
            for scenario in ("normal", "stress", "fatigue", "radiation_event")
            if scenario in SCENARIOS
        ]
    }


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("REPORT_PORT", "8001"))
    uvicorn.run("report.server:app", host="127.0.0.1", port=port, reload=True)
