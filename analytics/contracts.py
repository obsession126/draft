"""Versioned telemetry and analysis contract shared with the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

SCHEMA_VERSION: Final = "1.0"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    label: str
    unit: str
    category: str


FEATURES: Final[tuple[FeatureSpec, ...]] = (
    FeatureSpec("hr_bpm", "Heart rate", "bpm", "cardiovascular"),
    FeatureSpec("hrv_ms", "HRV (RMSSD)", "ms", "cardiovascular"),
    FeatureSpec("systolic_bp_mmhg", "Systolic blood pressure", "mmHg", "cardiovascular"),
    FeatureSpec("diastolic_bp_mmhg", "Diastolic blood pressure", "mmHg", "cardiovascular"),
    FeatureSpec("ecg_rr_interval_ms", "ECG-derived RR interval", "ms", "cardiovascular"),
    FeatureSpec("spo2_percent", "Blood oxygen saturation", "%", "respiratory"),
    FeatureSpec("respiratory_rate_bpm", "Respiratory rate", "breaths/min", "respiratory"),
    FeatureSpec("skin_temperature_c", "Skin temperature", "Cel", "thermoregulation"),
    FeatureSpec("sleep_duration_min", "Sleep duration", "min", "sleep"),
    FeatureSpec("sleep_midpoint_hour", "Sleep midpoint (mission-local)", "h", "sleep"),
    FeatureSpec("sleep_awakenings", "Sleep awakenings", "count", "sleep"),
    FeatureSpec("sleep_quality_1_5", "Self-reported sleep quality", "score_1_5", "sleep"),
    FeatureSpec("activity_duration_min", "Exercise duration", "min", "activity"),
    FeatureSpec("activity_type_code", "Activity type", "category_code", "activity"),
    FeatureSpec("activity_intensity_0_1", "Activity intensity", "ratio_0_1", "activity"),
    FeatureSpec("movement_rms_g", "Movement RMS", "g", "activity"),
    FeatureSpec("symptom_severity_0_10", "Self-reported symptom severity", "score_0_10", "self_report"),
    FeatureSpec("symptom_type_code", "Self-reported symptom category", "category_code", "self_report"),
    FeatureSpec("stress_self_report_0_10", "Self-reported stress", "score_0_10", "self_report"),
    FeatureSpec("mood_self_report_0_10", "Self-reported mood", "score_0_10", "self_report"),
    FeatureSpec("alertness_self_report_0_10", "Self-reported alertness", "score_0_10", "self_report"),
    FeatureSpec("radiation_dose_rate_usv_h", "Radiation dose rate", "uSv/h", "radiation"),
    FeatureSpec("cumulative_dose_usv", "Cumulative radiation dose", "uSv", "radiation"),
    FeatureSpec("cabin_temperature_c", "Cabin temperature", "Cel", "cabin_environment"),
    FeatureSpec("cabin_pressure_kpa", "Cabin pressure", "kPa", "cabin_environment"),
    FeatureSpec("cabin_humidity_percent", "Cabin relative humidity", "%", "cabin_environment"),
    FeatureSpec("lighting_lux", "Cabin illuminance", "lux", "cabin_environment"),
    FeatureSpec("noise_db", "Cabin noise level", "dB", "cabin_environment"),
    FeatureSpec("co2_ppm", "Cabin carbon dioxide", "ppm", "cabin_environment"),
    FeatureSpec("o2_percent", "Cabin oxygen fraction", "%", "cabin_environment"),
    FeatureSpec("bone_density_index", "Simulated bone-density index", "synthetic_index", "longitudinal"),
    FeatureSpec("muscle_mass_index", "Simulated muscle-mass index", "synthetic_index", "longitudinal"),
    FeatureSpec("oct_retinal_thickness_um", "Simulated OCT retinal thickness", "um", "research"),
    FeatureSpec("lab_inflammation_index", "Simulated lab inflammation marker", "synthetic_index", "research"),
    FeatureSpec("water_intake_ml", "Logged water intake", "ml", "nutrition"),
    FeatureSpec("energy_intake_kcal", "Logged energy intake", "kcal", "nutrition"),
)

FEATURE_BY_NAME: Final = {feature.name: feature for feature in FEATURES}
FEATURE_NAMES: Final[tuple[str, ...]] = tuple(feature.name for feature in FEATURES)
FEATURE_UNITS: Final = {feature.name: feature.unit for feature in FEATURES}

CONTEXT_FIELDS: Final = (
    "profile_id",
    "mission_elapsed_min",
    "mission_phase",
    "eva_active",
    "link_online",
    "countermeasure_type",
    "countermeasure_duration_min",
    "countermeasure_completed",
    "simulation_scenario",
)

ANALYSIS_VERSION: Final = "nonlinear-ensemble-v1"
