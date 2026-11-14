"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import type { CrewProfile } from "@/lib/api";
import { reportApi } from "@/lib/report-api";
import type { DailyReport, ReportHealth, ReportScenario, ReportScenarioId } from "@/lib/report-api";

type ReportWorkspaceProps = {
  token: string;
  profile: CrewProfile | undefined;
  missionDay: number;
};

function formatGeneratedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatMeasurement(value: number | null, unit: string) {
  return value == null ? "No data" : `${value.toLocaleString("en", { maximumFractionDigits: 2 })} ${unit}`;
}

function priorityLabel(priority: DailyReport["ai_analysis"]["medical_review"]["review_priority"]) {
  const labels = {
    ROUTINE: "Routine demo review",
    REVIEW: "Review flagged by demo bands",
    HIGH_ATTENTION: "High attention in demo scenario",
    DATA_LIMITED: "Limited simulated data",
  };
  return labels[priority];
}

export default function ReportWorkspace({ token, profile, missionDay }: ReportWorkspaceProps) {
  const [serviceHealth, setServiceHealth] = useState<ReportHealth | null>(null);
  const [scenarios, setScenarios] = useState<ReportScenario[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<ReportScenarioId>("normal");
  const [loadingService, setLoadingService] = useState(true);
  const [serviceError, setServiceError] = useState("");
  const [generationError, setGenerationError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [consentAccepted, setConsentAccepted] = useState(false);
  const [dailyReport, setDailyReport] = useState<DailyReport | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([reportApi.health(token), reportApi.scenarios(token)])
      .then(([health, availableScenarios]) => {
        if (!active) return;
        setServiceHealth(health);
        setScenarios(availableScenarios);
        setServiceError("");
      })
      .catch((error: unknown) => {
        if (active) {
          setServiceError(error instanceof Error ? error.message : "Could not connect to the report service.");
        }
      })
      .finally(() => {
        if (active) setLoadingService(false);
      });
    return () => {
      active = false;
    };
  }, [token]);

  const selectedScenarioDetails = scenarios.find((scenario) => scenario.id === selectedScenario);
  const previousByName = useMemo(
    () => new Map(dailyReport?.measurements.previous.map((measurement) => [measurement.name, measurement]) ?? []),
    [dailyReport],
  );
  const summaryByName = useMemo(
    () => new Map(dailyReport?.ai_analysis.vitals_summary.map((measurement) => [measurement.name, measurement]) ?? []),
    [dailyReport],
  );

  async function generateReport(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!profile || !consentAccepted || generating) return;
    setGenerating(true);
    setGenerationError("");
    setDailyReport(null);
    try {
      const report = await reportApi.generate(token, {
        profile_id: profile.profile_id,
        mission_day: missionDay,
        scenario: selectedScenario,
        consent: true,
      });
      setDailyReport(report);
    } catch (error) {
      setGenerationError(error instanceof Error ? error.message : "Report generation failed.");
    } finally {
      setGenerating(false);
    }
  }

  return (
    <div className="report-workspace">
      <section className="report-intro panel">
        <div>
          <p className="eyebrow">AI REPORT GENERATOR · SCENARIO SIMULATION</p>
          <h2>Daily health scenario report</h2>
          <p>
            Generate a structured narrative for a fresh synthetic dataset. The report
            does not analyze the measurements currently stored for this mission profile.
          </p>
        </div>
        <div className={`report-service-status ${serviceHealth?.status === "ok" ? "service-ready" : ""}`}>
          <span className="status-dot" />
          {loadingService ? "Checking report service…" :
            serviceHealth?.status === "ok" ? `Ready · ${serviceHealth.model}` :
              serviceHealth ? "Gemini configuration needed" : "Report service unavailable"}
        </div>
      </section>
      {serviceHealth && !serviceHealth.gemini_configured && (
        <div className="report-setup-note" role="status">
          Add a new <code>GEMINI_API_KEY</code> to <code>report/.env</code>, then restart the report service.
        </div>
      )}

      <form className="report-controls panel" onSubmit={generateReport}>
        <div className="report-context">
          <p className="eyebrow">MISSION CONTEXT</p>
          <strong>{profile?.display_name ?? "Crew profile unavailable"}</strong>
          <span>{profile?.mission_name ?? "Select a crew profile"} · Flight day {missionDay}</span>
          <small>Profile context labels the report; its measurements are generated separately.</small>
        </div>
        <label className="report-scenario-field">
          Scenario
          <select
            value={selectedScenario}
            disabled={loadingService || scenarios.length === 0 || generating}
            onChange={(event) => {
              const nextScenario = scenarios.find((scenario) => scenario.id === event.currentTarget.value);
              if (nextScenario) {
                setSelectedScenario(nextScenario.id);
                setDailyReport(null);
                setGenerationError("");
              }
            }}
          >
            {scenarios.map((scenario) => (
              <option key={scenario.id} value={scenario.id}>{scenario.label}</option>
            ))}
          </select>
          <small>{selectedScenarioDetails?.description ?? "Loading available scenarios…"}</small>
        </label>
        <label className="report-consent">
          <input
            type="checkbox"
            checked={consentAccepted}
            onChange={(event) => setConsentAccepted(event.target.checked)}
          />
          <span>
            I understand that generating this report sends the newly generated synthetic
            measurements and scenario context to Google AI Studio. Real telemetry is not
            included; crew name and profile ID are not sent to Gemini.
          </span>
        </label>
        {(serviceError || generationError) && (
          <div className="error-banner report-error" role="alert">{generationError || serviceError}</div>
        )}
        <div className="report-control-actions">
          <span>Each run creates a new randomized synthetic sample.</span>
          <button
            className="button button-primary"
            type="submit"
            disabled={loadingService || serviceHealth?.status !== "ok" || !profile || !consentAccepted || generating}
          >
            {generating ? "Generating report…" : "Generate daily report"}
          </button>
        </div>
      </form>

      {dailyReport && (
        <article className="daily-report" aria-labelledby="daily-report-title">
          <header className="daily-report-header">
            <div>
              <p className="eyebrow">SYNTHETIC SCENARIO · {dailyReport.metadata.scenario.replaceAll("_", " ")}</p>
              <h2 id="daily-report-title">Daily report</h2>
              <p>{dailyReport.astronaut.name} · {dailyReport.astronaut.mission_name} · Flight day {dailyReport.astronaut.mission_day} · {dailyReport.astronaut.mission_phase.replaceAll("_", " ")}</p>
              <small>Generated {formatGeneratedAt(dailyReport.generated_at)} · {dailyReport.report_id}</small>
            </div>
            <button className="button button-secondary report-print-button" onClick={() => window.print()} type="button">Print / Save PDF</button>
          </header>

          <div className="report-disclaimer" role="note">
            {dailyReport.metadata.disclaimer} The reference bands and review priority are
            illustrative software-demo values, not medical thresholds or clinical triage.
          </div>

          <section className="report-assessment-grid" aria-label="AI-generated report summary">
            <article className="report-section-card report-summary-card">
              <p className="eyebrow">GENERATED SUMMARY · {dailyReport.metadata.ai_model}</p>
              <h3>Scenario overview</h3>
              <p>{dailyReport.ai_analysis.daily_health_assessment.general_health_status}</p>
            </article>
            <article className="report-section-card">
              <p className="eyebrow">COMPARISON</p>
              <h3>Changes from previous sample</h3>
              <p>{dailyReport.ai_analysis.daily_health_assessment.changes_from_previous}</p>
            </article>
            <article className="report-section-card">
              <p className="eyebrow">OBSERVATIONS</p>
              <h3>Detected deviations</h3>
              <p>{dailyReport.ai_analysis.daily_health_assessment.detected_deviations}</p>
            </article>
            <article className="report-section-card">
              <p className="eyebrow">DEMO REVIEW FLAG</p>
              <h3>{priorityLabel(dailyReport.ai_analysis.medical_review.review_priority)}</h3>
              <p>Illustrative follow-up flag: {dailyReport.ai_analysis.medical_review.follow_up_required ? "yes" : "no"}.</p>
              <p>{dailyReport.ai_analysis.medical_review.priority_note}</p>
            </article>
          </section>

          <section className="report-detail-section">
            <div className="section-heading">
              <div><p className="eyebrow">22 SIMULATED INDICATORS</p><h3>Current and previous measurements</h3></div>
              <span className="section-note">Generated values · demo bands only</span>
            </div>
            <div className="report-table-wrap panel">
              <table className="daily-report-table">
                <thead>
                  <tr><th>Indicator</th><th>Current</th><th>Previous</th><th>Illustrative band</th><th>Status</th><th>Trend</th></tr>
                </thead>
                <tbody>
                  {dailyReport.measurements.current.map((measurement) => {
                    const previous = previousByName.get(measurement.name);
                    const summary = summaryByName.get(measurement.name);
                    return (
                      <tr key={measurement.name}>
                        <th scope="row">{measurement.indicator}</th>
                        <td>{formatMeasurement(measurement.value, measurement.unit)}</td>
                        <td>{formatMeasurement(previous?.value ?? null, previous?.unit ?? measurement.unit)}</td>
                        <td>{measurement.reference_range}</td>
                        <td><span className={`report-status report-status-${measurement.status.toLowerCase().replaceAll(" ", "-")}`}>{measurement.status}</span></td>
                        <td><span>{summary?.trend ?? "—"}</span><small>{summary?.note ?? ""}</small></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="report-guidance-grid">
            <article className="report-section-card">
              <p className="eyebrow">SUGGESTED DATA CHECKS</p>
              <h3>Recommended actions</h3>
              {dailyReport.ai_analysis.daily_health_assessment.recommended_actions.length ? (
                <ul>
                  {dailyReport.ai_analysis.daily_health_assessment.recommended_actions.map((action, index) => <li key={`${index}-${action}`}>{action}</li>)}
                </ul>
              ) : <p>No additional data checks were suggested for this scenario.</p>}
            </article>
            <article className="report-section-card">
              <p className="eyebrow">HUMAN REVIEW CONTEXT</p>
              <h3>Monitoring notes</h3>
              <p>{dailyReport.ai_analysis.medical_review.monitoring_officer_notes}</p>
              <h4>Question for a qualified reviewer</h4>
              <p>{dailyReport.ai_analysis.medical_review.clinician_review_prompt}</p>
              <small>{dailyReport.ai_analysis.medical_review.additional_notes}</small>
            </article>
          </section>

          <footer className="daily-report-footer">
            Synthetic scenario report · {dailyReport.metadata.ai_model} · Not a medical device or diagnosis
          </footer>
        </article>
      )}
    </div>
  );
}
