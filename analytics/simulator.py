"""Deterministic, explicitly synthetic telemetry source."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Final

from analytics.contracts import FEATURE_NAMES, FEATURE_UNITS

SUPPORTED_SCENARIOS: Final = (
    "demo",
    "normal",
    "interaction_shift",
    "gradual_drift",
    "sensor_artifact",
    "signal_loss",
    "radiation_event",
)


class TelemetrySimulator:
    """Generate correlated baseline telemetry and repeatable demo scenarios."""

    def __init__(self, seed: int = 42, profile_id: str = "crew-01") -> None:
        self.seed = seed
        self.profile_id = profile_id
        self._random = random.Random(seed)
        self._start_time = datetime.now(timezone.utc).replace(microsecond=0)

    def generate_normal_vector(self, sample_index: int) -> dict[str, float]:
        """Return one clean, correlated vector for calibration or streaming."""
        phase = sample_index * 0.17
        activity = min(1.0, max(0.0, 0.38 + 0.3 * math.sin(phase)))
        exertion_noise = self._random.gauss(0.0, 1.0)
        recovery_noise = self._random.gauss(0.0, 1.0)
        sleep_phase = (sample_index % 144) / 144
        values = {
            "hr_bpm": 64.0 + activity * 43.0 + exertion_noise * 2.2,
            "hrv_ms": 58.0 - activity * 22.0 + recovery_noise * 3.0,
            "systolic_bp_mmhg": 112.0 + activity * 10.0 + exertion_noise * 1.8,
            "diastolic_bp_mmhg": 72.0 + activity * 5.0 + recovery_noise * 1.4,
            "ecg_rr_interval_ms": 60_000.0 / (64.0 + activity * 43.0 + exertion_noise * 2.2),
            "spo2_percent": 97.8 + self._random.gauss(0.0, 0.35),
            "respiratory_rate_bpm": 12.0 + activity * 8.0 + self._random.gauss(0.0, 0.8),
            "skin_temperature_c": 33.2 + activity * 0.7 + self._random.gauss(0.0, 0.18),
            "sleep_duration_min": 425.0 + self._random.gauss(0.0, 16.0),
            "sleep_midpoint_hour": 3.2 + 0.45 * math.sin(sleep_phase * math.tau),
            "sleep_awakenings": max(0.0, 2.0 + self._random.gauss(0.0, 0.7)),
            "sleep_quality_1_5": min(5.0, max(1.0, 4.0 + self._random.gauss(0.0, 0.35))),
            "activity_duration_min": 35.0 + activity * 24.0 + self._random.gauss(0.0, 3.0),
            "activity_type_code": 1.0 if activity >= 0.2 else 0.0,
            "activity_intensity_0_1": activity,
            "movement_rms_g": 0.018 + activity * 0.12 + abs(self._random.gauss(0.0, 0.008)),
            "symptom_severity_0_10": max(0.0, 0.3 + abs(self._random.gauss(0.0, 0.25))),
            "symptom_type_code": 0.0,
            "stress_self_report_0_10": min(10.0, max(0.0, 2.0 + activity * 1.2 + self._random.gauss(0.0, 0.45))),
            "mood_self_report_0_10": min(10.0, max(0.0, 7.2 - activity * 0.25 + self._random.gauss(0.0, 0.45))),
            "alertness_self_report_0_10": min(10.0, max(0.0, 7.0 + self._random.gauss(0.0, 0.45))),
            "radiation_dose_rate_usv_h": max(0.0, 0.16 + self._random.gauss(0.0, 0.025)),
            "cumulative_dose_usv": 18.0 + sample_index * 0.00005,
            "cabin_temperature_c": 22.0 + self._random.gauss(0.0, 0.18),
            "cabin_pressure_kpa": 70.0 + self._random.gauss(0.0, 0.12),
            "cabin_humidity_percent": 42.0 + self._random.gauss(0.0, 1.2),
            "lighting_lux": 280.0 + 80.0 * math.sin(sleep_phase * math.tau) + self._random.gauss(0.0, 12.0),
            "noise_db": 48.0 + self._random.gauss(0.0, 1.2),
            "co2_ppm": 900.0 + self._random.gauss(0.0, 28.0),
            "o2_percent": 21.0 + self._random.gauss(0.0, 0.12),
            "bone_density_index": 1.0 + self._random.gauss(0.0, 0.012),
            "muscle_mass_index": 1.0 + self._random.gauss(0.0, 0.014),
            "oct_retinal_thickness_um": 252.0 + self._random.gauss(0.0, 2.5),
            "lab_inflammation_index": 1.0 + self._random.gauss(0.0, 0.08),
            "water_intake_ml": 2050.0 + self._random.gauss(0.0, 130.0),
            "energy_intake_kcal": 2250.0 + self._random.gauss(0.0, 110.0),
        }
        return values

    def generate(
        self,
        sample_index: int,
        scenario_mode: str = "demo",
        *,
        timestamp: datetime | None = None,
    ) -> dict[str, object]:
        """Return one contract-ready synthetic sample."""
        if scenario_mode not in SUPPORTED_SCENARIOS:
            raise ValueError(f"Unsupported scenario '{scenario_mode}'.")

        scenario = self._scenario_at(sample_index, scenario_mode)
        values = self.generate_normal_vector(sample_index)
        quality = {name: "good" for name in FEATURE_NAMES}
        mission_minutes = float(sample_index)

        if scenario == "interaction_shift":
            # Marginals remain individually plausible while their relationship breaks.
            values.update(
                hr_bpm=105.0 + self._random.gauss(0.0, 1.0),
                hrv_ms=31.0 + self._random.gauss(0.0, 1.0),
                activity_duration_min=40.0,
                activity_type_code=0.0,
                activity_intensity_0_1=0.03,
                movement_rms_g=0.022,
                respiratory_rate_bpm=13.0 + self._random.gauss(0.0, 0.5),
            )
        elif scenario == "gradual_drift":
            drift = min(1.0, (sample_index % 24 + 1) / 24)
            values["hr_bpm"] += 12.0 * drift
            values["hrv_ms"] -= 10.0 * drift
            values["sleep_duration_min"] -= 65.0 * drift
            values["stress_self_report_0_10"] += 3.0 * drift
            if drift >= 0.7:
                values["symptom_type_code"] = 1.0
                values["symptom_severity_0_10"] += 2.0 * drift
        elif scenario == "sensor_artifact":
            values["spo2_percent"] = 72.0
            quality["spo2_percent"] = "low"
        elif scenario == "signal_loss":
            values["spo2_percent"] = None
            quality["spo2_percent"] = "missing"
        elif scenario == "radiation_event":
            values["radiation_dose_rate_usv_h"] = 3.4
            values["cumulative_dose_usv"] += 2.8
            values["stress_self_report_0_10"] += 1.0

        sample_time = timestamp or self._start_time + timedelta(seconds=sample_index)
        recorded_at = datetime.now(timezone.utc).replace(microsecond=0)
        activity = float(values["activity_intensity_0_1"])
        context = {
            "profile_id": self.profile_id,
            "mission_elapsed_min": mission_minutes,
            "mission_phase": "transit",
            "eva_active": False,
            "link_online": scenario != "signal_loss",
            "countermeasure_type": "exercise",
            "countermeasure_duration_min": float(values["activity_duration_min"]),
            "countermeasure_completed": activity >= 0.55,
            "simulation_scenario": scenario,
        }
        return {
            "schema_version": "1.0",
            "event_id": f"{self.profile_id}-{sample_index:08d}",
            "measured_at": sample_time.isoformat().replace("+00:00", "Z"),
            "recorded_at": recorded_at.isoformat().replace("+00:00", "Z"),
            "source": "synthetic-simulator",
            "is_synthetic": True,
            "measurements": {
                name: {
                    "value": values[name],
                    "unit": _unit_for(name),
                    "quality": quality[name],
                    "source": "simulated",
                }
                for name in FEATURE_NAMES
            },
            "feature_names": list(FEATURE_NAMES),
            "feature_vector": [values[name] for name in FEATURE_NAMES],
            "context": context,
        }

    @staticmethod
    def _scenario_at(sample_index: int, mode: str) -> str:
        if mode != "demo":
            return mode
        phase = sample_index % 72
        if 16 <= phase < 24:
            return "interaction_shift"
        if 32 <= phase < 38:
            return "sensor_artifact"
        if 44 <= phase < 54:
            return "gradual_drift"
        if 58 <= phase < 62:
            return "signal_loss"
        if 64 <= phase < 68:
            return "radiation_event"
        return "normal"


def _unit_for(feature_name: str) -> str:
    return FEATURE_UNITS[feature_name]
