export type ReportScenarioId = "normal" | "stress" | "fatigue" | "radiation_event";

export type ReportScenario = {
  id: ReportScenarioId;
  label: string;
  description: string;
};

export type ReportHealth = {
  status: string;
  version: string;
  gemini_configured: boolean;
  model: string;
};

export type DailyReportMeasurement = {
  indicator: string;
  name: string;
  value: number | null;
  unit: string;
  status: string;
  reference_range: string;
};

export type DailyReport = {
  report_id: string;
  generated_at: string;
  astronaut: {
    name: string;
    profile_id: string;
    mission_name: string;
    mission_day: number;
    mission_phase: string;
  };
  measurements: {
    current: DailyReportMeasurement[];
    previous: DailyReportMeasurement[];
  };
  ai_analysis: {
    daily_health_assessment: {
      general_health_status: string;
      changes_from_previous: string;
      detected_deviations: string;
      recommended_actions: string[];
    };
    medical_review: {
      monitoring_officer_notes: string;
      clinician_review_prompt: string;
      additional_notes: string;
      review_priority: "ROUTINE" | "REVIEW" | "HIGH_ATTENTION" | "DATA_LIMITED";
      follow_up_required: boolean;
      priority_note: string;
    };
    vitals_summary: Array<{
      indicator: string;
      name: string;
      value: string;
      status: string;
      trend: "Stable" | "Increasing" | "Decreasing" | "New";
      note: string;
    }>;
  };
  metadata: {
    data_source: "synthetic_simulation";
    report_mode: "scenario_simulation";
    scenario: ReportScenarioId;
    ai_model: string;
    disclaimer: string;
  };
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isDailyReportMeasurement(value: unknown): value is DailyReportMeasurement {
  return (
    isRecord(value) &&
    isString(value.indicator) &&
    isString(value.name) &&
    (typeof value.value === "number" || value.value === null) &&
    isString(value.unit) &&
    isString(value.status) &&
    isString(value.reference_range)
  );
}

function isVitalsSummary(value: unknown): value is DailyReport["ai_analysis"]["vitals_summary"][number] {
  return (
    isRecord(value) &&
    isString(value.indicator) &&
    isString(value.name) &&
    isString(value.value) &&
    isString(value.status) &&
    (value.trend === "Stable" ||
      value.trend === "Increasing" ||
      value.trend === "Decreasing" ||
      value.trend === "New") &&
    isString(value.note)
  );
}

function isDailyReport(value: unknown): value is DailyReport {
  if (!isRecord(value)) return false;
  const astronaut = value.astronaut;
  const measurements = value.measurements;
  const analysis = value.ai_analysis;
  const metadata = value.metadata;
  if (
    !isString(value.report_id) ||
    !isString(value.generated_at) ||
    !isRecord(astronaut) ||
    !isRecord(measurements) ||
    !isRecord(analysis) ||
    !isRecord(metadata) ||
    !isRecord(analysis.daily_health_assessment) ||
    !isRecord(analysis.medical_review)
  ) {
    return false;
  }
  const assessment = analysis.daily_health_assessment;
  const review = analysis.medical_review;
  return (
    isString(astronaut.name) &&
    isString(astronaut.profile_id) &&
    isString(astronaut.mission_name) &&
    typeof astronaut.mission_day === "number" &&
    isString(astronaut.mission_phase) &&
    Array.isArray(measurements.current) &&
    measurements.current.every(isDailyReportMeasurement) &&
    Array.isArray(measurements.previous) &&
    measurements.previous.every(isDailyReportMeasurement) &&
    Array.isArray(analysis.vitals_summary) &&
    analysis.vitals_summary.every(isVitalsSummary) &&
    isString(assessment.general_health_status) &&
    isString(assessment.changes_from_previous) &&
    isString(assessment.detected_deviations) &&
    Array.isArray(assessment.recommended_actions) &&
    assessment.recommended_actions.every(isString) &&
    isString(review.monitoring_officer_notes) &&
    isString(review.clinician_review_prompt) &&
    isString(review.additional_notes) &&
    (review.review_priority === "ROUTINE" ||
      review.review_priority === "REVIEW" ||
      review.review_priority === "HIGH_ATTENTION" ||
      review.review_priority === "DATA_LIMITED") &&
    typeof review.follow_up_required === "boolean" &&
    isString(review.priority_note) &&
    isString(metadata.data_source) &&
    isString(metadata.report_mode) &&
    (metadata.scenario === "normal" ||
      metadata.scenario === "stress" ||
      metadata.scenario === "fatigue" ||
      metadata.scenario === "radiation_event") &&
    isString(metadata.ai_model) &&
    isString(metadata.disclaimer)
  );
}

async function requestReport(
  token: string,
  resource: "health" | "scenarios" | "generate",
  body?: unknown,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(
      resource === "generate"
        ? "/api/reports"
        : `/api/reports?resource=${resource}`,
      {
        method: resource === "generate" ? "POST" : "GET",
        headers: {
          Authorization: `Token ${token}`,
          Accept: "application/json",
          ...(resource === "generate" ? { "Content-Type": "application/json" } : {}),
        },
        body: resource === "generate" ? JSON.stringify(body) : undefined,
        cache: "no-store",
      },
    );
  } catch {
    throw new Error("Cannot reach the report API proxy.");
  }

  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const message = isRecord(payload) && isString(payload.error)
      ? payload.error
      : `Report request failed (${response.status}).`;
    throw new Error(message);
  }
  return payload;
}

export const reportApi = {
  async health(token: string): Promise<ReportHealth> {
    const payload = await requestReport(token, "health");
    if (
      !isRecord(payload) ||
      !isString(payload.status) ||
      !isString(payload.version) ||
      typeof payload.gemini_configured !== "boolean" ||
      !isString(payload.model)
    ) {
      throw new Error("The report service returned an invalid health response.");
    }
    return {
      status: payload.status,
      version: payload.version,
      gemini_configured: payload.gemini_configured,
      model: payload.model,
    };
  },

  async scenarios(token: string): Promise<ReportScenario[]> {
    const payload = await requestReport(token, "scenarios");
    if (!isRecord(payload) || !Array.isArray(payload.scenarios)) {
      throw new Error("The report service returned an invalid scenario list.");
    }
    const validScenarios = payload.scenarios.filter(
      (item): item is ReportScenario =>
        isRecord(item) &&
        (item.id === "normal" ||
          item.id === "stress" ||
          item.id === "fatigue" ||
          item.id === "radiation_event") &&
        isString(item.label) &&
        isString(item.description),
    );
    if (validScenarios.length !== payload.scenarios.length) {
      throw new Error("The report service returned an unsupported scenario.");
    }
    return validScenarios;
  },

  async generate(
    token: string,
    input: {
      profile_id: string;
      mission_day: number;
      scenario: ReportScenarioId;
      consent: true;
    },
  ): Promise<DailyReport> {
    const payload = await requestReport(token, "generate", input);
    if (!isDailyReport(payload)) {
      throw new Error("The report service returned an incomplete report.");
    }
    return payload;
  },
};
