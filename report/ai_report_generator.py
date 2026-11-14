"""
AI-генератор щоденних звітів про здоров'я астронавта.
Використовує Google Gemini API для створення медичних висновків.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Optional

from google import genai

from report.simulator_data import DailyHealthData, VitalReading, generate_simulated_data


# ──────────────────────────────────────────────────────────
#  Gemini client
# ──────────────────────────────────────────────────────────

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "AIzaSyB8RN6KMFtXKMw04MgA0quHKVjdp-Uo7m7ZVRkWxyebFyXbdNA",
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# ──────────────────────────────────────────────────────────
#  Побудова prompt-тексту з даних телеметрії
# ──────────────────────────────────────────────────────────

REPORT_TEMPLATE = """
You are a flight surgeon AI assistant for a space mission health monitoring system.
Generate a comprehensive daily health assessment report for the astronaut based on
the telemetry data provided below.

## Astronaut Information
- Name: {astronaut_name}
- Profile ID: {profile_id}
- Mission: {mission_name}
- Mission Day: {mission_day}
- Mission Phase: {mission_phase}
- Report Time: {timestamp}

## Current Vital Signs & Measurements

{vitals_table}

## Previous Day Measurements (for comparison)

{previous_vitals_table}

## Instructions

Based on the data above, provide a structured medical assessment in the following JSON format.
Do NOT wrap the response in markdown code fences. Return only valid JSON.

{{
  "daily_health_assessment": {{
    "general_health_status": "<Overall health status assessment — 2-3 sentences in Ukrainian>",
    "changes_from_previous": "<Comparison with previous measurements — what changed and how, in Ukrainian>",
    "detected_deviations": "<Any detected deviations or anomalies, in Ukrainian>",
    "recommended_actions": "<Recommended actions for the medical team, in Ukrainian>"
  }},
  "medical_review": {{
    "monitoring_officer_notes": "<Notes from monitoring officer perspective, in Ukrainian>",
    "flight_surgeon_review": "<Flight surgeon assessment and recommendations, in Ukrainian>",
    "additional_notes": "<Any additional medical notes or observations, in Ukrainian>",
    "risk_level": "<LOW | MODERATE | HIGH | CRITICAL>",
    "follow_up_required": <true or false>
  }},
  "vitals_summary": [
    {{
      "indicator": "<Indicator name>",
      "value": "<Measured value with unit>",
      "status": "<Normal | Warning | Critical>",
      "trend": "<Stable | Increasing | Decreasing | New>",
      "note": "<Brief note about this indicator, in Ukrainian>"
    }}
  ]
}}

Be thorough, clinically precise, and note that this is a SIMULATED environment.
All status assessments should be relative to space-medicine standards.
Respond ONLY with valid JSON — no markdown fences, no extra text.
"""


def _format_vitals_table(vitals: list[VitalReading]) -> str:
    """Форматування таблиці показників для prompt."""
    lines = ["| Indicator | Value | Unit | Status | Reference Range |",
             "|-----------|-------|------|--------|-----------------|"]
    for v in vitals:
        value_str = f"{v.value}" if v.value is not None else "N/A"
        lines.append(f"| {v.label} | {value_str} | {v.unit} | {v.status} | {v.reference_range} |")
    return "\n".join(lines)


def _build_prompt(data: DailyHealthData) -> str:
    """Побудова повного prompt для Gemini."""
    return REPORT_TEMPLATE.format(
        astronaut_name=data.astronaut_name,
        profile_id=data.profile_id,
        mission_name=data.mission_name,
        mission_day=data.mission_day,
        mission_phase=data.mission_phase,
        timestamp=data.timestamp,
        vitals_table=_format_vitals_table(data.vitals),
        previous_vitals_table=_format_vitals_table(data.previous_vitals),
    )


# ──────────────────────────────────────────────────────────
#  Генерація звіту через Gemini
# ──────────────────────────────────────────────────────────

def generate_daily_report(
    astronaut_name: str = "Crew Member 01",
    profile_id: str = "crew-01",
    mission_name: str = "Demo Mission",
    mission_day: int | None = None,
    mission_phase: str = "transit",
    scenario: str = "normal",
) -> dict:
    """
    Генерація повного щоденного звіту про здоров'я.

    1. Симулює дані телеметрії
    2. Відправляє їх до Gemini API
    3. Отримує структурований медичний висновок
    4. Повертає повний звіт з усіма даними
    """
    # 1. Отримати симульовані дані
    health_data = generate_simulated_data(
        astronaut_name=astronaut_name,
        profile_id=profile_id,
        mission_name=mission_name,
        mission_day=mission_day,
        mission_phase=mission_phase,
        scenario=scenario,
    )

    # 2. Побудувати prompt і отримати AI-аналіз
    prompt = _build_prompt(health_data)
    ai_analysis = _call_gemini(prompt)

    # 3. Зібрати повний звіт
    report = {
        "report_id": f"RPT-{profile_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "astronaut": {
            "name": health_data.astronaut_name,
            "profile_id": health_data.profile_id,
            "mission_name": health_data.mission_name,
            "mission_day": health_data.mission_day,
            "mission_phase": health_data.mission_phase,
        },
        "measurements": {
            "current": [
                {
                    "indicator": v.label,
                    "name": v.name,
                    "value": v.value,
                    "unit": v.unit,
                    "status": v.status,
                    "reference_range": v.reference_range,
                }
                for v in health_data.vitals
            ],
            "previous": [
                {
                    "indicator": v.label,
                    "name": v.name,
                    "value": v.value,
                    "unit": v.unit,
                    "status": v.status,
                    "reference_range": v.reference_range,
                }
                for v in health_data.previous_vitals
            ],
        },
        "ai_analysis": ai_analysis,
        "metadata": {
            "data_source": "synthetic_simulation",
            "ai_model": "gemini-2.0-flash",
            "disclaimer": "This report is generated from SIMULATED data and is NOT for clinical use.",
        },
    }

    return report


def _call_gemini(prompt: str) -> dict:
    """Виклик Gemini API і парсинг відповіді."""
    try:
        client = _get_client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )

        raw_text = response.text.strip()

        # Видалити можливі markdown code fences
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            # Прибрати першу лінію ```json та останню ```
            start = 1
            end = len(lines) - 1
            if lines[-1].strip() == "```":
                raw_text = "\n".join(lines[start:end])
            else:
                raw_text = "\n".join(lines[start:])

        return json.loads(raw_text)

    except json.JSONDecodeError:
        return {
            "daily_health_assessment": {
                "general_health_status": "AI-аналіз отримано, але відповідь неструктурована.",
                "changes_from_previous": raw_text[:500] if 'raw_text' in dir() else "Помилка парсингу",
                "detected_deviations": "Потрібна ручна перевірка",
                "recommended_actions": "Повторити генерацію звіту",
            },
            "medical_review": {
                "monitoring_officer_notes": "Автоматичний аналіз потребує перевірки",
                "flight_surgeon_review": "Необхідна ручна оцінка",
                "additional_notes": raw_text[:1000] if 'raw_text' in dir() else "",
                "risk_level": "MODERATE",
                "follow_up_required": True,
            },
            "vitals_summary": [],
            "_raw_response": raw_text if 'raw_text' in dir() else None,
        }
    except Exception as exc:
        return {
            "daily_health_assessment": {
                "general_health_status": f"Помилка AI-аналізу: {exc}",
                "changes_from_previous": "Недоступно",
                "detected_deviations": "Недоступно",
                "recommended_actions": "Перевірити API-ключ та з'єднання",
            },
            "medical_review": {
                "monitoring_officer_notes": f"Помилка: {exc}",
                "flight_surgeon_review": "Потрібна ручна оцінка",
                "additional_notes": "",
                "risk_level": "MODERATE",
                "follow_up_required": True,
            },
            "vitals_summary": [],
            "_error": str(exc),
        }
