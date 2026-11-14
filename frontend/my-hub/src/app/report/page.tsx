"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";

/* ─── types ─── */
type Measurement = {
  indicator: string;
  name: string;
  value: number | null;
  unit: string;
  status: string;
  reference_range: string;
};

type VitalsSummaryItem = {
  indicator: string;
  value: string;
  status: string;
  trend: string;
  note: string;
};

type DailyAssessment = {
  general_health_status: string;
  changes_from_previous: string;
  detected_deviations: string;
  recommended_actions: string;
};

type MedicalReview = {
  monitoring_officer_notes: string;
  flight_surgeon_review: string;
  additional_notes: string;
  risk_level: string;
  follow_up_required: boolean;
};

type HealthReport = {
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
    current: Measurement[];
    previous: Measurement[];
  };
  ai_analysis: {
    daily_health_assessment: DailyAssessment;
    medical_review: MedicalReview;
    vitals_summary: VitalsSummaryItem[];
  };
  metadata: {
    data_source: string;
    ai_model: string;
    disclaimer: string;
  };
};

type Scenario = {
  id: string;
  label: string;
  description: string;
};

/* ─── auth helpers (same as main page) ─── */
const AUTH_EVENT = "mission-auth-change";

function subscribeToToken(onChange: () => void) {
  window.addEventListener(AUTH_EVENT, onChange);
  return () => window.removeEventListener(AUTH_EVENT, onChange);
}
function getTokenSnapshot() {
  return window.sessionStorage.getItem("mission-api-token") ?? "";
}
function getServerTokenSnapshot() {
  return "";
}

/* ─── Report API base ─── */
const REPORT_API = (
  process.env.NEXT_PUBLIC_REPORT_API_URL ?? "http://127.0.0.1:8001"
).replace(/\/+$/, "");

/* ─── helpers ─── */
function formatDateTime(iso: string | undefined) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("uk-UA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

function statusBadgeClass(status: string) {
  switch (status.toLowerCase()) {
    case "normal":
      return "report-badge report-badge-normal";
    case "warning":
      return "report-badge report-badge-warning";
    case "critical":
      return "report-badge report-badge-critical";
    default:
      return "report-badge";
  }
}

function riskBadgeClass(risk: string) {
  switch (risk) {
    case "LOW":
      return "report-risk report-risk-low";
    case "MODERATE":
      return "report-risk report-risk-moderate";
    case "HIGH":
      return "report-risk report-risk-high";
    case "CRITICAL":
      return "report-risk report-risk-critical";
    default:
      return "report-risk";
  }
}

function trendIcon(trend: string) {
  switch (trend?.toLowerCase()) {
    case "increasing":
      return "↑";
    case "decreasing":
      return "↓";
    case "stable":
      return "→";
    default:
      return "•";
  }
}

/* ─── category grouping ─── */
const CATEGORY_MAP: Record<string, string> = {
  hr_bpm: "Cardiovascular",
  hrv_ms: "Cardiovascular",
  systolic_bp_mmhg: "Cardiovascular",
  diastolic_bp_mmhg: "Cardiovascular",
  ecg_rr_interval_ms: "Cardiovascular",
  spo2_percent: "Respiratory",
  respiratory_rate_bpm: "Respiratory",
  skin_temperature_c: "Thermoregulation",
  sleep_duration_min: "Sleep",
  sleep_quality_1_5: "Sleep",
  activity_duration_min: "Activity",
  stress_self_report_0_10: "Self Report",
  mood_self_report_0_10: "Self Report",
  alertness_self_report_0_10: "Self Report",
  radiation_dose_rate_usv_h: "Radiation",
  cabin_temperature_c: "Cabin Environment",
  cabin_pressure_kpa: "Cabin Environment",
  cabin_humidity_percent: "Cabin Environment",
  co2_ppm: "Cabin Environment",
  o2_percent: "Cabin Environment",
  water_intake_ml: "Nutrition",
  energy_intake_kcal: "Nutrition",
};

/* ─── component ─── */
export default function ReportPage() {
  const token = useSyncExternalStore(subscribeToToken, getTokenSnapshot, getServerTokenSnapshot);

  const [report, setReport] = useState<HealthReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [selectedScenario, setSelectedScenario] = useState("normal");
  const [astronautName, setAstronautName] = useState("Crew Member 01");
  const [profileId, setProfileId] = useState("crew-01");
  const [missionName, setMissionName] = useState("Demo Mission");
  const [missionPhase, setMissionPhase] = useState("transit");

  /* fetch scenarios on mount */
  useEffect(() => {
    fetch(`${REPORT_API}/api/report/scenarios/`)
      .then((r) => r.json())
      .then((data) => setScenarios(data.scenarios ?? []))
      .catch(() => {
        setScenarios([
          { id: "normal", label: "Normal", description: "" },
          { id: "stress", label: "Stress", description: "" },
          { id: "fatigue", label: "Fatigue", description: "" },
          { id: "radiation_event", label: "Radiation Event", description: "" },
        ]);
      });
  }, []);

  const generateReport = useCallback(async () => {
    setLoading(true);
    setError("");
    setReport(null);
    try {
      const res = await fetch(`${REPORT_API}/api/report/generate/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          astronaut_name: astronautName,
          profile_id: profileId,
          mission_name: missionName,
          mission_phase: missionPhase,
          scenario: selectedScenario,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail ?? `HTTP ${res.status}`);
      }
      const data: HealthReport = await res.json();
      setReport(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate report.");
    } finally {
      setLoading(false);
    }
  }, [astronautName, profileId, missionName, missionPhase, selectedScenario]);

  /* group current measurements by category */
  const groupedMeasurements = useMemo(() => {
    if (!report) return new Map<string, Measurement[]>();
    const map = new Map<string, Measurement[]>();
    for (const m of report.measurements.current) {
      const cat = CATEGORY_MAP[m.name] ?? "Other";
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(m);
    }
    return map;
  }, [report]);

  /* build a lookup for previous readings */
  const prevLookup = useMemo(() => {
    if (!report) return new Map<string, Measurement>();
    return new Map(report.measurements.previous.map((m) => [m.name, m]));
  }, [report]);

  /* stats */
  const normalCount = report?.measurements.current.filter((m) => m.status === "Normal").length ?? 0;
  const warningCount = report?.measurements.current.filter((m) => m.status === "Warning").length ?? 0;
  const criticalCount = report?.measurements.current.filter((m) => m.status === "Critical").length ?? 0;
  const totalCount = report?.measurements.current.length ?? 0;

  return (
    <main className="app-shell">
      {/* ─── sidebar ─── */}
      <aside className="sidebar">
        <a className="brand-lockup" href="/" aria-label="Orbital Health home">
          <span className="brand-mark">O</span>
          <span>ORBITAL <b>HEALTH</b></span>
        </a>
        <div className="side-label">MISSION CONTROL</div>
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-item" href="/"><span>◫</span> Overview</a>
          <a className="nav-item nav-active" href="/report"><span>📋</span> Daily Report</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="system-card">
            <div className="system-card-title"><span className="status-dot status-dot-green" /> REPORT GENERATOR</div>
            <p>Data source</p><strong>Synthetic simulation</strong>
            <p>AI Engine</p><strong>Gemini 2.0 Flash</strong>
            <span className="system-foot">Not clinically validated</span>
          </div>
        </div>
      </aside>

      {/* ─── main content ─── */}
      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumb">MISSION CONTROL <span>/</span> DAILY HEALTH REPORT</div>
          <div className="topbar-right">
            <span className="environment-tag">SYNTHETIC ENVIRONMENT</span>
          </div>
        </header>

        <div className="content">
          {/* ─── page title ─── */}
          <section className="page-heading">
            <div>
              <p className="eyebrow">ЩОДЕННИЙ ЗВІТ ПРО ЗДОРОВ&apos;Я АСТРОНАВТА</p>
              <h1>Daily Health Report</h1>
              <p className="muted">Генерація AI-звіту на основі симульованих даних телеметрії з медичними висновками.</p>
            </div>
          </section>

          {/* ─── report config form ─── */}
          <section className="section-block">
            <div className="section-heading">
              <div><p className="eyebrow">ПАРАМЕТРИ ЗВІТУ</p><h2>Configuration</h2></div>
            </div>
            <div className="panel report-config-panel">
              <div className="report-config-grid">
                <label>
                  <span className="report-field-label">Astronaut Name</span>
                  <input value={astronautName} onChange={(e) => setAstronautName(e.target.value)} />
                </label>
                <label>
                  <span className="report-field-label">Profile ID</span>
                  <input value={profileId} onChange={(e) => setProfileId(e.target.value)} />
                </label>
                <label>
                  <span className="report-field-label">Mission Name</span>
                  <input value={missionName} onChange={(e) => setMissionName(e.target.value)} />
                </label>
                <label>
                  <span className="report-field-label">Mission Phase</span>
                  <select value={missionPhase} onChange={(e) => setMissionPhase(e.target.value)}>
                    <option value="transit">Transit</option>
                    <option value="surface">Surface</option>
                    <option value="return">Return</option>
                  </select>
                </label>
                <label>
                  <span className="report-field-label">Simulation Scenario</span>
                  <select value={selectedScenario} onChange={(e) => setSelectedScenario(e.target.value)}>
                    {scenarios.map((s) => (
                      <option key={s.id} value={s.id}>{s.label}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="report-config-actions">
                <button className="button button-primary" onClick={generateReport} disabled={loading}>
                  {loading ? "⟳ Генерація звіту…" : "📋 Згенерувати щоденний звіт"}
                </button>
              </div>
            </div>
          </section>

          {/* ─── error ─── */}
          {error && <div className="error-banner page-error" role="alert">{error}</div>}

          {/* ─── loading ─── */}
          {loading && (
            <div className="panel report-loading-panel">
              <div className="report-loading">
                <div className="report-spinner" />
                <p>Генерація звіту через Gemini AI…</p>
                <small>Це може зайняти 10-20 секунд</small>
              </div>
            </div>
          )}

          {/* ─── report content ─── */}
          {report && !loading && (
            <>
              {/* header card */}
              <section className="section-block">
                <div className="panel report-header-panel">
                  <div className="report-header-top">
                    <div>
                      <p className="eyebrow">ЗВІТ #{report.report_id}</p>
                      <h2>{report.astronaut.name} — Mission Day {report.astronaut.mission_day}</h2>
                      <p className="muted">{report.astronaut.mission_name} · Phase: {report.astronaut.mission_phase} · {formatDateTime(report.generated_at)}</p>
                    </div>
                    <div className={riskBadgeClass(report.ai_analysis.medical_review.risk_level)}>
                      {report.ai_analysis.medical_review.risk_level}
                    </div>
                  </div>
                  <div className="report-stat-row">
                    <div className="report-stat"><span>Total Indicators</span><strong>{totalCount}</strong></div>
                    <div className="report-stat report-stat-normal"><span>Normal</span><strong>{normalCount}</strong></div>
                    <div className="report-stat report-stat-warning"><span>Warning</span><strong>{warningCount}</strong></div>
                    <div className="report-stat report-stat-critical"><span>Critical</span><strong>{criticalCount}</strong></div>
                    <div className="report-stat"><span>Follow-up</span><strong>{report.ai_analysis.medical_review.follow_up_required ? "YES" : "NO"}</strong></div>
                  </div>
                </div>
              </section>

              {/* vitals table – template format */}
              <section className="section-block">
                <div className="section-heading">
                  <div><p className="eyebrow">ПОКАЗНИКИ ЗДОРОВ&apos;Я</p><h2>Health Indicators</h2></div>
                  <span className="section-note">{totalCount} indicators measured</span>
                </div>
                <div className="panel table-panel">
                  <div className="report-vitals-table">
                    <div className="report-vitals-head">
                      <span>Indicator</span>
                      <span>Result</span>
                      <span>Previous</span>
                      <span>Change</span>
                      <span>Status</span>
                      <span>Reference</span>
                    </div>
                    {report.measurements.current.map((m) => {
                      const prev = prevLookup.get(m.name);
                      const delta = m.value != null && prev?.value != null ? m.value - prev.value : null;
                      return (
                        <div className="report-vitals-row" key={m.name}>
                          <span className="report-indicator-name">{m.indicator}</span>
                          <span className="report-indicator-value">{m.value != null ? `${m.value} ${m.unit}` : "—"}</span>
                          <span className="report-indicator-prev">{prev?.value != null ? `${prev.value} ${prev.unit}` : "—"}</span>
                          <span className={`report-indicator-delta ${delta && delta > 0 ? "delta-up" : delta && delta < 0 ? "delta-down" : ""}`}>
                            {delta != null ? `${delta > 0 ? "+" : ""}${delta.toFixed(2)}` : "—"}
                          </span>
                          <span><span className={statusBadgeClass(m.status)}>{m.status}</span></span>
                          <span className="report-ref">{m.reference_range}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </section>

              {/* AI vitals summary table */}
              {report.ai_analysis.vitals_summary?.length > 0 && (
                <section className="section-block">
                  <div className="section-heading">
                    <div><p className="eyebrow">AI ОЦІНКА ПОКАЗНИКІВ</p><h2>AI Vitals Summary</h2></div>
                  </div>
                  <div className="panel table-panel">
                    <div className="report-ai-table">
                      <div className="report-ai-head">
                        <span>Indicator</span>
                        <span>Value</span>
                        <span>Status</span>
                        <span>Trend</span>
                        <span>Note</span>
                      </div>
                      {report.ai_analysis.vitals_summary.map((item, i) => (
                        <div className="report-ai-row" key={i}>
                          <span>{item.indicator}</span>
                          <span className="report-indicator-value">{item.value}</span>
                          <span><span className={statusBadgeClass(item.status)}>{item.status}</span></span>
                          <span className="report-trend">{trendIcon(item.trend)} {item.trend}</span>
                          <span className="report-note">{item.note}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </section>
              )}

              {/* Daily Health Assessment */}
              <section className="section-block">
                <div className="section-heading">
                  <div><p className="eyebrow">ЩОДЕННА ОЦІНКА ЗДОРОВ&apos;Я</p><h2>Daily Health Assessment</h2></div>
                </div>
                <div className="report-assessment-grid">
                  <article className="panel report-assessment-card">
                    <h3>🩺 Загальний стан здоров&apos;я</h3>
                    <p>{report.ai_analysis.daily_health_assessment.general_health_status}</p>
                  </article>
                  <article className="panel report-assessment-card">
                    <h3>📊 Зміни порівняно з попередніми вимірюваннями</h3>
                    <p>{report.ai_analysis.daily_health_assessment.changes_from_previous}</p>
                  </article>
                  <article className="panel report-assessment-card">
                    <h3>⚠️ Виявлені відхилення</h3>
                    <p>{report.ai_analysis.daily_health_assessment.detected_deviations}</p>
                  </article>
                  <article className="panel report-assessment-card">
                    <h3>💊 Рекомендовані дії медичної команди</h3>
                    <p>{report.ai_analysis.daily_health_assessment.recommended_actions}</p>
                  </article>
                </div>
              </section>

              {/* Medical Review */}
              <section className="section-block">
                <div className="section-heading">
                  <div><p className="eyebrow">МЕДИЧНИЙ ОГЛЯД</p><h2>Medical Review</h2></div>
                  <div className={riskBadgeClass(report.ai_analysis.medical_review.risk_level)}>
                    Risk: {report.ai_analysis.medical_review.risk_level}
                  </div>
                </div>
                <div className="panel report-review-panel">
                  <div className="report-review-grid">
                    <div className="report-review-item">
                      <span className="report-review-label">Monitoring Officer</span>
                      <p>{report.ai_analysis.medical_review.monitoring_officer_notes}</p>
                    </div>
                    <div className="report-review-item">
                      <span className="report-review-label">Flight Surgeon Review</span>
                      <p>{report.ai_analysis.medical_review.flight_surgeon_review}</p>
                    </div>
                    <div className="report-review-item report-review-full">
                      <span className="report-review-label">Additional Notes</span>
                      <p>{report.ai_analysis.medical_review.additional_notes}</p>
                    </div>
                  </div>
                  {report.ai_analysis.medical_review.follow_up_required && (
                    <div className="report-followup-banner">
                      ⚡ Follow-up required — Необхідно подальше спостереження
                    </div>
                  )}
                </div>
              </section>

              {/* metadata / disclaimer */}
              <section className="section-block">
                <div className="panel report-disclaimer-panel">
                  <p className="eyebrow">DISCLAIMER</p>
                  <p>{report.metadata.disclaimer}</p>
                  <div className="report-meta-row">
                    <span>Data source: <b>{report.metadata.data_source}</b></span>
                    <span>AI model: <b>{report.metadata.ai_model}</b></span>
                    <span>Report ID: <b>{report.report_id}</b></span>
                  </div>
                </div>
              </section>

              <footer className="page-footer">
                <span>ORBITAL HEALTH · DAILY REPORT v1.0</span>
                <span>SIMULATED DATA · NOT FOR CLINICAL USE</span>
              </footer>
            </>
          )}
        </div>
      </section>
    </main>
  );
}
