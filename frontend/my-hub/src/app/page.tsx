"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  Alert,
  CrewProfile,
  Dashboard,
  Feature,
  missionApi,
} from "@/lib/api";

type EventRecord = NonNullable<Dashboard["latest"]>;

const FEATURE_SHORTLIST = ["hr_bpm", "hrv_ms", "spo2_percent", "sleep_duration_min"];
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

function notifyTokenChanged() {
  window.dispatchEvent(new Event(AUTH_EVENT));
}

function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("en", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(value));
}

function formatValue(value: number | null | undefined, digits = 1) {
  return value == null ? "—" : value.toFixed(digits);
}

function statusLabel(status: string) {
  return status.replaceAll("_", " ");
}

function StatusMark({ status }: { status: string }) {
  return (
    <span className={`status-mark status-${status}`}>
      <span className="status-dot" />
      {statusLabel(status)}
    </span>
  );
}

function TrendChart({
  values,
  color,
  label,
}: {
  values: Array<number | null>;
  color: string;
  label: string;
}) {
  const points = values.filter((value): value is number => value != null);
  if (points.length < 2) {
    return <div className="chart-empty">Waiting for more measurements</div>;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const spread = max - min || 1;
  const coordinates = points.map((value, index) => {
    const x = (index / (points.length - 1)) * 100;
    const y = 44 - ((value - min) / spread) * 34;
    return `${x},${y}`;
  });
  const areaPath = `M ${coordinates[0]} L ${coordinates.slice(1).join(" L ")} L 100,52 L 0,52 Z`;

  return (
    <div className="chart-wrap" role="img" aria-label={`${label} trend, ${points.length} measurements`}>
      <div className="chart-scale">
        <span>{formatValue(max)}</span>
        <span>{formatValue(min)}</span>
      </div>
      <svg viewBox="0 0 100 56" preserveAspectRatio="none" className="trend-chart">
        <defs>
          <linearGradient id="trend-fill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity=".22" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d="M 0,10 H 100 M 0,27 H 100 M 0,44 H 100" className="chart-grid" />
        <path d={areaPath} fill="url(#trend-fill)" />
        <polyline points={coordinates.join(" ")} fill="none" stroke={color} strokeWidth="1.25" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="chart-axis">
        <span>Oldest</span>
        <span>Latest</span>
      </div>
    </div>
  );
}

function MetricCard({
  title,
  measurement,
  icon,
  accent,
  timestamp,
}: {
  title: string;
  measurement?: { value: number | null; unit: string; quality: string };
  icon: string;
  accent: string;
  timestamp?: string;
}) {
  return (
    <article className="metric-card" style={{ "--metric-accent": accent } as React.CSSProperties}>
      <div className="metric-top">
        <span className="metric-icon">{icon}</span>
        <span className={`quality-tag quality-${measurement?.quality ?? "missing"}`}>
          {measurement?.quality ?? "no data"}
        </span>
      </div>
      <p className="metric-label">{title}</p>
      <div className="metric-value">
        {formatValue(measurement?.value)}
        <span>{measurement?.unit ?? "—"}</span>
      </div>
      <p className="metric-time">Updated {formatTime(timestamp)}</p>
    </article>
  );
}

function SignInScreen({
  onLogin,
  error,
  busy,
}: {
  onLogin: (username: string, password: string) => Promise<void>;
  error: string;
  busy: boolean;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await onLogin(username, password);
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="brand-lockup">
          <span className="brand-mark">O</span>
          <span>ORBITAL <b>HEALTH</b></span>
        </div>
        <p className="eyebrow">MISSION HEALTH SYSTEM · LOCAL DEMO</p>
        <h1>Welcome back.</h1>
        <p className="auth-copy">Sign in to access your crew telemetry and mission health dashboard.</p>
        <form className="form-stack" onSubmit={submit}>
          <label>
            Username
            <input autoComplete="username" required value={username} onChange={(event) => setUsername(event.target.value)} />
          </label>
          <label>
            Password
            <input autoComplete="current-password" required type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
          </label>
          {error && <p className="error-banner" role="alert">{error}</p>}
          <button className="button button-primary button-wide" disabled={busy}>
            {busy ? "Connecting…" : "Sign in to mission control"}
            <span aria-hidden="true">→</span>
          </button>
        </form>
        <div className="auth-foot"><span className="status-dot status-dot-green" /> Secure local API connection</div>
      </section>
      <aside className="auth-visual">
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
        <div className="planet" />
        <div className="visual-caption">
          <span>DEEP SPACE HEALTH SYSTEM</span>
          <strong>See the signal<br />before it becomes<br /><i>the story.</i></strong>
          <small>Personal baselines. Explainable patterns.<br />Crew-first decisions.</small>
        </div>
      </aside>
    </main>
  );
}

export default function Home() {
  const token = useSyncExternalStore(subscribeToToken, getTokenSnapshot, getServerTokenSnapshot);
  const [busy, setBusy] = useState(false);
  const [apiError, setApiError] = useState("");
  const [profiles, setProfiles] = useState<CrewProfile[]>([]);
  const [profileId, setProfileId] = useState("");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [seriesValues, setSeriesValues] = useState<Array<number | null>>([]);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertCount, setAlertCount] = useState(0);
  const [alertTotalCount, setAlertTotalCount] = useState(0);
  const [alertPage, setAlertPage] = useState(1);
  const [alertHasNext, setAlertHasNext] = useState(false);
  const [eventTotalCount, setEventTotalCount] = useState(0);
  const [eventPage, setEventPage] = useState(1);
  const [eventHasNext, setEventHasNext] = useState(false);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [selectedFeature, setSelectedFeature] = useState("hr_bpm");
  const [showProfileForm, setShowProfileForm] = useState(false);

  const loadProfiles = useCallback(async (activeToken: string) => {
    const [availableProfiles, catalog] = await Promise.all([
      missionApi.profiles(activeToken),
      missionApi.catalog(activeToken),
    ]);
    setProfiles(availableProfiles);
    setFeatures(catalog.features);
    setProfileId((current) =>
      availableProfiles.some((profile) => profile.profile_id === current)
        ? current
        : availableProfiles[0]?.profile_id ?? "",
    );
    setShowProfileForm(availableProfiles.length === 0);
  }, []);

  const refresh = useCallback(async () => {
    if (!token || !profileId) return;
    try {
      const [nextDashboard, nextSeries, nextEvents, nextAlerts, openAlerts] = await Promise.all([
        missionApi.dashboard(token, profileId),
        missionApi.series(token, profileId, selectedFeature),
        missionApi.events(token, profileId, eventPage),
        missionApi.alerts(token, profileId, alertPage),
        missionApi.alerts(token, profileId, 1, "open"),
      ]);
      setDashboard(nextDashboard);
      setSeriesValues(nextSeries.points.map((point) => point.value));
      setEvents(nextEvents.results.filter((event): event is EventRecord => event !== null));
      setAlerts(nextAlerts.results);
      setAlertCount(openAlerts.count);
      setAlertTotalCount(nextAlerts.count);
      setAlertHasNext(nextAlerts.next !== null);
      setEventTotalCount(nextEvents.count);
      setEventHasNext(nextEvents.next !== null);
      setApiError("");
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not refresh mission data.");
    }
  }, [alertPage, eventPage, profileId, selectedFeature, token]);

  useEffect(() => {
    if (!token) return;
    let active = true;
    void Promise.all([missionApi.profiles(token), missionApi.catalog(token)])
      .then(([availableProfiles, catalog]) => {
        if (!active) return;
        setProfiles(availableProfiles);
        setFeatures(catalog.features);
        setProfileId((current) =>
          availableProfiles.some((profile) => profile.profile_id === current)
            ? current
            : availableProfiles[0]?.profile_id ?? "",
        );
        setShowProfileForm(availableProfiles.length === 0);
      })
      .catch((error: unknown) => {
        if (active) {
          setApiError(error instanceof Error ? error.message : "Could not load crew profiles.");
        }
      });
    return () => {
      active = false;
    };
  }, [token]);

  useEffect(() => {
    if (!token || !profileId) return;
    const initialRefresh = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, [profileId, refresh, token]);

  const latestPayload = dashboard?.latest?.payload;
  const selectedFeatureMeta = useMemo(
    () => features.find((feature) => feature.name === selectedFeature),
    [features, selectedFeature],
  );
  const isLoggedIn = Boolean(token);

  async function signIn(username: string, password: string) {
    setBusy(true);
    setApiError("");
    try {
      const { token: nextToken } = await missionApi.login(username, password);
      window.sessionStorage.setItem("mission-api-token", nextToken);
      notifyTokenChanged();
    } catch (error) {
      window.sessionStorage.removeItem("mission-api-token");
      notifyTokenChanged();
      setApiError(error instanceof Error ? error.message : "Sign in failed.");
    } finally {
      setBusy(false);
    }
  }

  async function createProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;
    const formData = new FormData(event.currentTarget);
    setBusy(true);
    setApiError("");
    try {
      const profile = await missionApi.createProfile(token, {
        profile_id: String(formData.get("profile_id")).trim(),
        display_name: String(formData.get("display_name")).trim(),
        mission_name: String(formData.get("mission_name")).trim(),
        mission_phase: String(formData.get("mission_phase")),
      });
      setProfiles((current) => [...current, profile]);
      setProfileId(profile.profile_id);
      setShowProfileForm(false);
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not create crew profile.");
    } finally {
      setBusy(false);
    }
  }

  async function updateAlert(alert: Alert, action: "acknowledge" | "resolve") {
    if (!token) return;
    try {
      await missionApi.updateAlert(token, alert.alert_id, action);
      await refresh();
    } catch (error) {
      setApiError(error instanceof Error ? error.message : "Could not update alert.");
    }
  }

  function signOut() {
    window.sessionStorage.removeItem("mission-api-token");
    notifyTokenChanged();
    setProfiles([]);
    setProfileId("");
    setAlertPage(1);
    setEventPage(1);
    setDashboard(null);
    setApiError("");
  }

  if (!isLoggedIn) return <SignInScreen onLogin={signIn} error={apiError} busy={busy} />;

  if (showProfileForm) {
    return (
      <main className="profile-setup">
        <div className="brand-lockup"><span className="brand-mark">O</span><span>ORBITAL <b>HEALTH</b></span></div>
        <section className="setup-card">
          <p className="eyebrow">MISSION CONFIGURATION · STEP 01</p>
          <h1>Create a crew profile</h1>
          <p className="muted">Telemetry will be stored against this profile and only visible to your account.</p>
          <form className="form-stack" onSubmit={createProfile}>
            <label>Profile ID<input name="profile_id" required defaultValue="crew-01" pattern="[A-Za-z0-9_-]+" /></label>
            <label>Display name<input name="display_name" required defaultValue="Crew Member 01" /></label>
            <label>Mission name<input name="mission_name" defaultValue="Demo mission" /></label>
            <label>Mission phase
              <select name="mission_phase" defaultValue="transit">
                <option value="transit">Transit</option><option value="surface">Surface</option><option value="return">Return</option>
              </select>
            </label>
            {apiError && <p className="error-banner" role="alert">{apiError}</p>}
            <button className="button button-primary" disabled={busy}>{busy ? "Creating…" : "Create profile"}<span>→</span></button>
          </form>
          <button className="text-button" onClick={signOut}>Sign out</button>
        </section>
      </main>
    );
  }

  if (!profileId) {
    return (
      <main className="profile-setup">
        <div className="brand-lockup"><span className="brand-mark">O</span><span>ORBITAL <b>HEALTH</b></span></div>
        <section className="setup-card">
          <p className="eyebrow">MISSION CONFIGURATION</p>
          <h1>Loading crew profile</h1>
          <p className="muted">{apiError || "Checking the authenticated account and its profiles."}</p>
          <button className="button button-secondary" onClick={() => void loadProfiles(token).catch((error: unknown) => setApiError(error instanceof Error ? error.message : "Could not load crew profiles."))}>Retry connection</button>
          <button className="text-button" onClick={signOut}>Sign out</button>
        </section>
      </main>
    );
  }

  const profile = profiles.find((item) => item.profile_id === profileId);
  const measurements = latestPayload?.measurements;
  const healthStatus = dashboard?.latest?.analysis_status ?? "insufficient_data";
  const statusColor = healthStatus === "normal" ? "#56d6a0" : "#ffad69";

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand-lockup" href="#" aria-label="Orbital Health home">
          <span className="brand-mark">O</span><span>ORBITAL <b>HEALTH</b></span>
        </a>
        <div className="side-label">MISSION CONTROL</div>
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-item nav-active" href="#overview"><span>◫</span> Overview</a>
          <a className="nav-item" href="#signals"><span>⌁</span> Signal trends</a>
          <a className="nav-item" href="#alerts"><span>◉</span> Alerts <b className="nav-count">{alertCount}</b></a>
          <a className="nav-item" href="#events"><span>≋</span> Event history</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="system-card">
            <div className="system-card-title"><span className="status-dot status-dot-green" /> SIMULATOR PIPELINE</div>
            <p>Data source</p><strong>Synthetic telemetry</strong>
            <p>Analysis</p><strong>Nonlinear ensemble</strong>
            <span className="system-foot">Not clinically validated</span>
          </div>
          <button className="nav-item signout-button" onClick={signOut}><span>↪</span> Sign out</button>
        </div>
      </aside>

      <section className="main-panel">
        <header className="topbar">
          <div className="breadcrumb">MISSION CONTROL <span>/</span> CREW HEALTH</div>
          <div className="topbar-right">
            <span className="environment-tag">SYNTHETIC ENVIRONMENT</span>
            <div className="user-chip"><span className="avatar">{profile?.display_name.slice(0, 1) ?? "C"}</span><span>{profile?.display_name ?? "Crew"}</span></div>
          </div>
        </header>

        <div className="content" id="overview">
          <section className="page-heading">
            <div>
              <p className="eyebrow">FLIGHT DAY {Math.max(1, Math.floor((latestPayload?.context.mission_elapsed_min ?? 0) / 1440) + 1)} <span>·</span> {profile?.mission_name || "MISSION"} </p>
              <h1>Crew health overview</h1>
              <p className="muted">A live view of personal signals, data quality, and explainable changes.</p>
            </div>
            <div className="heading-actions">
              {profiles.length > 1 && (
                <select aria-label="Select crew profile" value={profileId} onChange={(event) => {
                  setProfileId(event.target.value);
                  setAlertPage(1);
                  setEventPage(1);
                }}>
                  {profiles.map((item) => <option key={item.profile_id} value={item.profile_id}>{item.display_name}</option>)}
                </select>
              )}
              <button className="button button-secondary" onClick={() => void refresh()}>↻ <span>Refresh</span></button>
            </div>
          </section>

          {apiError && <div className="error-banner page-error" role="alert">{apiError}</div>}

          <section className="summary-grid" aria-label="Mission and analysis status">
            <article className="summary-card status-summary">
              <div className="summary-label">ANALYSIS STATUS <span>ⓘ</span></div>
              <div className="summary-status"><StatusMark status={healthStatus} /></div>
              <p>{latestPayload?.analysis.explanation ?? "Waiting for telemetry from the simulator pipeline."}</p>
              <div className="summary-foot">Relative to synthetic baseline · not a diagnosis</div>
            </article>
            <article className="summary-card">
              <div className="summary-label">MISSION LINK <span className="summary-icon">⌁</span></div>
              <div className="summary-big"><span className={`link-indicator ${latestPayload?.context.link_online ? "link-on" : ""}`} />{latestPayload?.context.link_online ? "Connected" : "Signal lost"}</div>
              <p>Mission telemetry source</p>
              <div className="summary-foot">Scenario: {latestPayload?.context.simulation_scenario ?? "awaiting data"}</div>
            </article>
            <article className="summary-card">
              <div className="summary-label">DATA FRESHNESS <span className="summary-icon">◷</span></div>
              <div className="summary-big">{dashboard?.sync_status === "current" ? "Live" : dashboard?.sync_status === "stale" ? "Delayed" : "No data"}</div>
              <p>Last received {formatTime(dashboard?.last_sync_at)}</p>
              <div className="summary-foot">Total events stored <b>{dashboard?.event_count ?? 0}</b></div>
            </article>
            <article className="summary-card alert-summary">
              <div className="summary-label">OPEN REVIEWS <span className="summary-icon">◉</span></div>
              <div className="summary-big">{alertCount.toString().padStart(2, "0")} <small>needs attention</small></div>
              <p>Review model-flagged patterns and signal quality.</p>
              <a className="summary-link" href="#alerts">Review alerts <span>→</span></a>
            </article>
          </section>

          <section className="section-block">
            <div className="section-heading">
              <div><p className="eyebrow">CURRENT READINGS</p><h2>Key health signals</h2></div>
              <span className="section-note">Measurement time {formatTime(dashboard?.latest?.measured_at)}</span>
            </div>
            <div className="metrics-grid">
              <MetricCard title="Heart rate" measurement={measurements?.hr_bpm} icon="♡" accent="#f27f80" timestamp={dashboard?.latest?.measured_at} />
              <MetricCard title="Heart rate variability" measurement={measurements?.hrv_ms} icon="⌁" accent="#84a7ff" timestamp={dashboard?.latest?.measured_at} />
              <MetricCard title="Blood oxygen" measurement={measurements?.spo2_percent} icon="◌" accent="#6ac8c3" timestamp={dashboard?.latest?.measured_at} />
              <MetricCard title="Sleep duration" measurement={measurements?.sleep_duration_min} icon="☾" accent="#bd9bfa" timestamp={dashboard?.latest?.measured_at} />
            </div>
          </section>

          <section className="section-block analytics-layout" id="signals">
            <article className="panel trend-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">PERSONAL SIGNAL HISTORY</p><h2>Trend explorer</h2></div>
                <select aria-label="Select signal to chart" value={selectedFeature} onChange={(event) => setSelectedFeature(event.target.value)}>
                  {features.filter((feature) => FEATURE_SHORTLIST.includes(feature.name) || feature.category === selectedFeatureMeta?.category).map((feature) => (
                    <option key={feature.name} value={feature.name}>{feature.label}</option>
                  ))}
                </select>
              </div>
              <div className="chart-summary">
                <strong>{formatValue(measurements?.[selectedFeature]?.value)} <small>{selectedFeatureMeta?.unit ?? measurements?.[selectedFeature]?.unit}</small></strong>
                <span>Latest · {selectedFeatureMeta?.label ?? selectedFeature}</span>
              </div>
              <TrendChart values={seriesValues} color={statusColor} label={selectedFeatureMeta?.label ?? selectedFeature} />
              <div className="chart-disclaimer">Values are shown as received. No interpolation is applied to missing measurements.</div>
            </article>

            <article className="panel analysis-panel">
              <div className="panel-heading"><div><p className="eyebrow">EXPLAINABLE ANALYSIS</p><h2>Why this status?</h2></div><span className="analysis-orbit">✳</span></div>
              <div className="analysis-intro"><StatusMark status={healthStatus} /><span>Detector · {latestPayload?.analysis.detector ?? "awaiting data"}</span></div>
              <p className="analysis-explanation">{latestPayload?.analysis.explanation ?? "A personal baseline and analysis will appear after the first sensor event."}</p>
              <div className="analysis-stats">
                <div><span>ANOMALY SCORE</span><strong>{latestPayload?.analysis.score == null ? "—" : `${(latestPayload.analysis.score * 100).toFixed(0)}%`}</strong><small>Empirical rank, not probability</small></div>
                <div><span>DATA QUALITY</span><strong>{latestPayload?.analysis.data_quality.status ?? "—"}</strong><small>{latestPayload ? `${Math.round(latestPayload.analysis.data_quality.valid_fraction * 100)}% valid features` : "No sample received"}</small></div>
              </div>
              {!!latestPayload?.analysis.top_contributors.length && (
                <div className="contributor-list">
                  <span className="mini-label">TOP CONTRIBUTING SIGNALS · RELATIVE MAGNITUDE</span>
                  {latestPayload.analysis.top_contributors.slice(0, 3).map((item) => {
                    const maxDeviation = Math.max(
                      ...latestPayload.analysis.top_contributors.map((contributor) => contributor.deviation_magnitude),
                      0.001,
                    );
                    const label = item.features
                      .map((name) => features.find((feature) => feature.name === name)?.label ?? name.replaceAll("_", " "))
                      .join(" × ");
                    return (
                    <div className="contributor-row" key={item.label}>
                      <span>{label}</span>
                      <div className="contributor-track"><i style={{ width: `${Math.min(100, Math.max(4, (item.deviation_magnitude / maxDeviation) * 100))}%` }} /></div>
                      <b>{item.deviation_magnitude.toFixed(1)}</b>
                    </div>
                    );
                  })}
                </div>
              )}
            </article>
          </section>

          <section className="section-block" id="alerts">
            <div className="section-heading">
              <div><p className="eyebrow">REVIEW QUEUE</p><h2>Health alerts <span className="heading-count">{alertTotalCount}</span></h2></div>
              <span className="section-note">{alerts.length ? `Showing ${alerts.length} of ${alertTotalCount} alerts` : "Alerts are generated from every non-normal analysis state."}</span>
            </div>
            <div className="panel table-panel">
              {alerts.length === 0 ? (
                <div className="empty-state"><span>✓</span><strong>No alerts to review</strong><p>Non-normal analysis results will be listed here with their evidence.</p></div>
              ) : (
                <div className="alert-list">
                  {alerts.map((alert) => (
                    <article className="alert-row" key={alert.alert_id}>
                      <span className={`alert-symbol alert-${alert.status}`}>{alert.status === "resolved" ? "✓" : "!"}</span>
                      <div className="alert-copy"><strong>{alert.title}</strong><p>{alert.explanation}</p><small>{formatTime(alert.measured_at)} · Event {alert.event_id}</small></div>
                      <StatusMark status={alert.status} />
                      <div className="alert-actions">
                        {alert.status === "open" && <button className="button button-secondary button-small" onClick={() => void updateAlert(alert, "acknowledge")}>Acknowledge</button>}
                        {alert.status !== "resolved" && <button className="text-button" onClick={() => void updateAlert(alert, "resolve")}>Resolve</button>}
                      </div>
                    </article>
                  ))}
                  <div className="pagination-row">
                    <button className="button button-secondary button-small" disabled={alertPage <= 1} onClick={() => setAlertPage((page) => page - 1)}>Previous</button>
                    <span>Page {alertPage} of {Math.max(1, Math.ceil(alertTotalCount / 20))}</span>
                    <button className="button button-secondary button-small" disabled={!alertHasNext} onClick={() => setAlertPage((page) => page + 1)}>Next</button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="section-block" id="events">
            <div className="section-heading"><div><p className="eyebrow">AUDIT TRAIL</p><h2>Recent telemetry events</h2></div><span className="section-note">Showing {events.length} of {eventTotalCount} · full 36-feature payload retained</span></div>
            <div className="panel table-panel">
              <div className="event-table">
                <div className="event-row event-head"><span>EVENT</span><span>MEASURED AT</span><span>SCENARIO</span><span>ANALYSIS</span><span>SCORE</span></div>
                {events.map((event) => (
                  <div className="event-row" key={event.event_id}>
                    <span className="event-id">{event.event_id}</span><span>{formatTime(event.measured_at)}</span><span className="scenario-name">{event.payload.context.simulation_scenario}</span><span><StatusMark status={event.analysis_status} /></span><span>{event.anomaly_score == null ? "—" : `${(event.anomaly_score * 100).toFixed(0)}%`}</span>
                  </div>
                ))}
                {events.length === 0 && <div className="empty-table">No events stored yet. Start the mission simulator to generate telemetry.</div>}
                <div className="pagination-row">
                  <button className="button button-secondary button-small" disabled={eventPage <= 1} onClick={() => setEventPage((page) => page - 1)}>Previous</button>
                  <span>Page {eventPage} of {Math.max(1, Math.ceil(eventTotalCount / 8))}</span>
                  <button className="button button-secondary button-small" disabled={!eventHasNext} onClick={() => setEventPage((page) => page + 1)}>Next</button>
                </div>
              </div>
            </div>
          </section>

          <footer className="page-footer"><span>ORBITAL HEALTH · API SCHEMA {dashboard?.schema_version ?? "1.0"}</span><span>SIMULATED DATA · NOT FOR CLINICAL USE</span></footer>
        </div>
      </section>
    </main>
  );
}
