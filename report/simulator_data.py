"""
Симуляція даних телеметрії для щоденного звіту про здоров'я астронавта.
Генерує реалістичні показники з рандомізованими відхиленнями.
"""

from __future__ import annotations

import random
import math
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class VitalReading:
    """Один показник вимірювання."""
    name: str
    label: str
    value: float | None
    unit: str
    status: str  # "Normal", "Warning", "Critical", "No Data"
    reference_range: str


@dataclass
class DailyHealthData:
    """Повний набір щоденних вимірювань здоров'я астронавта."""
    astronaut_name: str
    profile_id: str
    mission_name: str
    mission_day: int
    mission_phase: str
    timestamp: str
    vitals: list[VitalReading] = field(default_factory=list)
    previous_vitals: list[VitalReading] = field(default_factory=list)


# Нормальні діапазони для всіх показників
VITAL_RANGES = {
    "hr_bpm": {"label": "Heart Rate", "unit": "bpm", "min": 55, "max": 100, "warn_low": 50, "warn_high": 110, "crit_low": 40, "crit_high": 130, "ref": "55–100 bpm"},
    "systolic_bp_mmhg": {"label": "Systolic BP", "unit": "mmHg", "min": 100, "max": 135, "warn_low": 90, "warn_high": 145, "crit_low": 80, "crit_high": 160, "ref": "100–135 mmHg"},
    "diastolic_bp_mmhg": {"label": "Diastolic BP", "unit": "mmHg", "min": 60, "max": 85, "warn_low": 55, "warn_high": 92, "crit_low": 45, "crit_high": 100, "ref": "60–85 mmHg"},
    "spo2_percent": {"label": "Oxygen Saturation", "unit": "%", "min": 95, "max": 100, "warn_low": 93, "warn_high": 101, "crit_low": 90, "crit_high": 101, "ref": "95–100%"},
    "respiratory_rate_bpm": {"label": "Respiratory Rate", "unit": "breaths/min", "min": 12, "max": 20, "warn_low": 10, "warn_high": 24, "crit_low": 8, "crit_high": 30, "ref": "12–20 breaths/min"},
    "skin_temperature_c": {"label": "Body Temperature", "unit": "°C", "min": 36.1, "max": 37.2, "warn_low": 35.5, "warn_high": 37.8, "crit_low": 35.0, "crit_high": 38.5, "ref": "36.1–37.2 °C"},
    "sleep_duration_min": {"label": "Sleep Duration", "unit": "min", "min": 360, "max": 540, "warn_low": 300, "warn_high": 600, "crit_low": 240, "crit_high": 660, "ref": "360–540 min (6–9 h)"},
    "activity_duration_min": {"label": "Physical Activity", "unit": "min", "min": 30, "max": 90, "warn_low": 15, "warn_high": 120, "crit_low": 0, "crit_high": 150, "ref": "30–90 min"},
    "stress_self_report_0_10": {"label": "Stress Level", "unit": "/10", "min": 0, "max": 4, "warn_low": -1, "warn_high": 6, "crit_low": -1, "crit_high": 8, "ref": "0–4 /10"},
    "hrv_ms": {"label": "Heart Rate Variability", "unit": "ms", "min": 35, "max": 80, "warn_low": 25, "warn_high": 90, "crit_low": 15, "crit_high": 100, "ref": "35–80 ms"},
    "ecg_rr_interval_ms": {"label": "ECG RR Interval", "unit": "ms", "min": 600, "max": 1100, "warn_low": 500, "warn_high": 1200, "crit_low": 400, "crit_high": 1400, "ref": "600–1100 ms"},
    "sleep_quality_1_5": {"label": "Sleep Quality", "unit": "/5", "min": 3, "max": 5, "warn_low": 2, "warn_high": 5.1, "crit_low": 1, "crit_high": 5.1, "ref": "3–5 /5"},
    "mood_self_report_0_10": {"label": "Mood Self-Report", "unit": "/10", "min": 5, "max": 10, "warn_low": 3, "warn_high": 10.1, "crit_low": 1, "crit_high": 10.1, "ref": "5–10 /10"},
    "alertness_self_report_0_10": {"label": "Alertness", "unit": "/10", "min": 5, "max": 10, "warn_low": 3, "warn_high": 10.1, "crit_low": 1, "crit_high": 10.1, "ref": "5–10 /10"},
    "radiation_dose_rate_usv_h": {"label": "Radiation Dose Rate", "unit": "μSv/h", "min": 0.05, "max": 0.3, "warn_low": -1, "warn_high": 0.5, "crit_low": -1, "crit_high": 1.0, "ref": "0.05–0.3 μSv/h"},
    "cabin_temperature_c": {"label": "Cabin Temperature", "unit": "°C", "min": 20, "max": 24, "warn_low": 18, "warn_high": 26, "crit_low": 15, "crit_high": 30, "ref": "20–24 °C"},
    "cabin_pressure_kpa": {"label": "Cabin Pressure", "unit": "kPa", "min": 69, "max": 71, "warn_low": 67, "warn_high": 73, "crit_low": 65, "crit_high": 75, "ref": "69–71 kPa"},
    "cabin_humidity_percent": {"label": "Cabin Humidity", "unit": "%", "min": 35, "max": 55, "warn_low": 25, "warn_high": 65, "crit_low": 20, "crit_high": 75, "ref": "35–55%"},
    "co2_ppm": {"label": "CO₂ Level", "unit": "ppm", "min": 700, "max": 1000, "warn_low": 500, "warn_high": 1200, "crit_low": 400, "crit_high": 1500, "ref": "700–1000 ppm"},
    "o2_percent": {"label": "O₂ Level", "unit": "%", "min": 20.5, "max": 21.5, "warn_low": 19.5, "warn_high": 22.5, "crit_low": 18.0, "crit_high": 23.5, "ref": "20.5–21.5%"},
    "water_intake_ml": {"label": "Water Intake", "unit": "ml", "min": 1800, "max": 2500, "warn_low": 1500, "warn_high": 3000, "crit_low": 1000, "crit_high": 3500, "ref": "1800–2500 ml"},
    "energy_intake_kcal": {"label": "Energy Intake", "unit": "kcal", "min": 2000, "max": 2600, "warn_low": 1700, "warn_high": 3000, "crit_low": 1400, "crit_high": 3500, "ref": "2000–2600 kcal"},
}


def _evaluate_status(value: float, spec: dict) -> str:
    """Визначити статус показника на основі діапазонів."""
    if value is None:
        return "No Data"
    if value < spec["crit_low"] or value > spec["crit_high"]:
        return "Critical"
    if value < spec["warn_low"] or value > spec["warn_high"]:
        return "Warning"
    if spec["min"] <= value <= spec["max"]:
        return "Normal"
    return "Warning"


def generate_simulated_data(
    astronaut_name: str = "Crew Member 01",
    profile_id: str = "crew-01",
    mission_name: str = "Demo Mission",
    mission_day: int | None = None,
    mission_phase: str = "transit",
    scenario: str = "normal",
    seed: int | None = None,
) -> DailyHealthData:
    """
    Генерація симульованих даних здоров'я астронавта за один день.
    Повертає поточні та попередні дані для порівняння.
    """
    if seed is not None:
        random.seed(seed)

    if mission_day is None:
        mission_day = random.randint(1, 365)

    now = datetime.now(timezone.utc)

    # Генерація поточних показників
    vitals: list[VitalReading] = []
    previous_vitals: list[VitalReading] = []

    for key, spec in VITAL_RANGES.items():
        center = (spec["min"] + spec["max"]) / 2
        spread = (spec["max"] - spec["min"]) / 2

        # Базове значення з нормальним розподілом
        value = center + random.gauss(0, spread * 0.35)

        # Сценарні модифікації
        if scenario == "stress":
            if key in ("hr_bpm", "stress_self_report_0_10", "respiratory_rate_bpm"):
                value += spread * 0.6
            if key in ("hrv_ms", "sleep_quality_1_5", "mood_self_report_0_10"):
                value -= spread * 0.4
        elif scenario == "fatigue":
            if key in ("sleep_duration_min", "alertness_self_report_0_10"):
                value -= spread * 0.7
            if key == "stress_self_report_0_10":
                value += spread * 0.3
        elif scenario == "radiation_event":
            if key == "radiation_dose_rate_usv_h":
                value = 2.5 + random.gauss(0, 0.3)
            if key == "stress_self_report_0_10":
                value += 1.5

        # Обмеження значення
        value = max(0, round(value, 2))

        status = _evaluate_status(value, spec)
        vitals.append(VitalReading(
            name=key,
            label=spec["label"],
            value=value,
            unit=spec["unit"],
            status=status,
            reference_range=spec["ref"],
        ))

        # Попередні значення (вчорашні) — трохи інші
        prev_value = center + random.gauss(0, spread * 0.3)
        prev_value = max(0, round(prev_value, 2))
        prev_status = _evaluate_status(prev_value, spec)
        previous_vitals.append(VitalReading(
            name=key,
            label=spec["label"],
            value=prev_value,
            unit=spec["unit"],
            status=prev_status,
            reference_range=spec["ref"],
        ))

    return DailyHealthData(
        astronaut_name=astronaut_name,
        profile_id=profile_id,
        mission_name=mission_name,
        mission_day=mission_day,
        mission_phase=mission_phase,
        timestamp=now.isoformat(),
        vitals=vitals,
        previous_vitals=previous_vitals,
    )
