const API_BASE_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");

export type AnalysisStatus =
  | "normal"
  | "anomaly_review"
  | "data_quality_review"
  | "insufficient_data";

export type Measurement = {
  value: number | null;
  unit: string;
  quality: "good" | "low" | "missing" | string;
  source: string;
};

export type TelemetryPayload = {
  schema_version: string;
  event_id: string;
  measured_at: string;
  recorded_at: string;
  source: string;
  is_synthetic: boolean;
  feature_names: string[];
  feature_vector: Array<number | null>;
  measurements: Record<string, Measurement>;
  context: {
    profile_id: string;
    mission_elapsed_min: number;
    mission_phase: string;
    link_online: boolean;
    simulation_scenario: string;
    [key: string]: unknown;
  };
  analysis: {
    status: AnalysisStatus;
    score: number | null;
    score_kind: string;
    threshold: number | null;
    detector: string;
    explanation: string;
    top_contributors: Array<{
      features: string[];
      label: string;
      deviation_magnitude: number;
      kind: "feature" | "interaction" | string;
    }>;
    data_quality: {
      status: string;
      valid_fraction: number;
      missing_features: string[];
      low_quality_features: string[];
    };
  };
};

export type CrewProfile = {
  profile_id: string;
  display_name: string;
  mission_name: string;
  mission_phase: string;
  created_at: string;
  updated_at: string;
};

export type Alert = {
  alert_id: string;
  profile_id: string;
  event_id: string;
  measured_at: string;
  status: "open" | "acknowledged" | "resolved";
  title: string;
  explanation: string;
  evidence: Record<string, unknown>;
  created_at: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
};

export type Dashboard = {
  schema_version: string;
  profile: CrewProfile;
  latest: {
    event_id: string;
    measured_at: string;
    received_at: string;
    analysis_status: AnalysisStatus;
    anomaly_score: number | null;
    payload: TelemetryPayload;
  } | null;
  open_alerts: Alert[];
  event_count: number;
  last_sync_at: string | null;
  sync_status: "no_data" | "stale" | "current";
};

export type Feature = {
  name: string;
  label: string;
  unit: string;
  category: string;
};

export type Series = {
  profile_id: string;
  feature: Feature;
  points: Array<{
    event_id: string;
    measured_at: string;
    value: number | null;
    unit: string;
    quality: string;
    analysis_status: AnalysisStatus;
  }>;
  count: number;
};

export type Paginated<T> = {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
};

async function request<T>(
  path: string,
  token?: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Token ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...options,
      headers,
      cache: "no-store",
    });
  } catch {
    throw new Error(
      `Cannot reach the mission API at ${API_BASE_URL}. Start the backend and check NEXT_PUBLIC_API_BASE_URL.`,
    );
  }

  const responseBody = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof responseBody?.detail === "string"
        ? responseBody.detail
        : JSON.stringify(responseBody ?? `HTTP ${response.status}`);
    throw new Error(`API ${response.status}: ${detail}`);
  }
  return responseBody as T;
}

export const missionApi = {
  login: (username: string, password: string) =>
    request<{ token: string }>("/api/v1/auth/token/", undefined, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),

  profiles: (token: string) => request<CrewProfile[]>("/api/v1/profiles/", token),

  createProfile: (
    token: string,
    profile: Pick<CrewProfile, "profile_id" | "display_name" | "mission_name" | "mission_phase">,
  ) =>
    request<CrewProfile>("/api/v1/profiles/", token, {
      method: "POST",
      body: JSON.stringify(profile),
    }),

  dashboard: (token: string, profileId: string) =>
    request<Dashboard>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}/dashboard/`,
      token,
    ),

  series: (token: string, profileId: string, feature: string) =>
    request<Series>(
      `/api/v1/profiles/${encodeURIComponent(profileId)}/series/?feature=${encodeURIComponent(feature)}&limit=48`,
      token,
    ),

  events: (token: string, profileId: string, page = 1) =>
    request<Paginated<Dashboard["latest"]>>(
      `/api/v1/telemetry/events/?profile_id=${encodeURIComponent(profileId)}&page_size=8&page=${page}`,
      token,
    ),

  alerts: (token: string, profileId: string, page = 1, status?: string) =>
    request<Paginated<Alert>>(
      `/api/v1/alerts/?profile_id=${encodeURIComponent(profileId)}&page_size=20&page=${page}${status ? `&status=${encodeURIComponent(status)}` : ""}`,
      token,
    ),

  catalog: (token: string) =>
    request<{ schema_version: string; features: Feature[] }>(
      "/api/v1/metadata/parameters/",
      token,
    ),

  updateAlert: (token: string, alertId: string, action: "acknowledge" | "resolve") =>
    request<Alert>(`/api/v1/alerts/${encodeURIComponent(alertId)}/${action}/`, token, {
      method: "POST",
      body: JSON.stringify({}),
    }),
};
