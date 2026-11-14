import type { CrewProfile } from "@/lib/api";

const REPORT_API_URL = process.env.REPORT_API_URL ?? "http://127.0.0.1:8001";
const MISSION_API_URL = (
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000"
).replace(/\/+$/, "");
const MAX_BODY_BYTES = 16 * 1024;
const SCENARIOS = new Set(["normal", "stress", "fatigue", "radiation_event"]);

function jsonError(error: string, status: number) {
  return Response.json({ error }, { status, headers: { "Cache-Control": "no-store" } });
}

function getAuthorization(request: Request) {
  const authorization = request.headers.get("authorization");
  return authorization && /^Token\s+\S+$/.test(authorization) ? authorization : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isCrewProfile(value: unknown): value is CrewProfile {
  return (
    isRecord(value) &&
    typeof value.profile_id === "string" &&
    typeof value.display_name === "string" &&
    typeof value.mission_name === "string" &&
    typeof value.mission_phase === "string"
  );
}

async function proxyReport(path: string, init: RequestInit = {}) {
  let endpoint: URL;
  try {
    endpoint = new URL(path, REPORT_API_URL);
    if (!["http:", "https:"].includes(endpoint.protocol)) {
      return jsonError("REPORT_API_URL must use HTTP or HTTPS.", 500);
    }
  } catch {
    return jsonError("REPORT_API_URL must be a valid HTTP(S) URL.", 500);
  }

  let upstream: Response;
  try {
    upstream = await fetch(endpoint, {
      ...init,
      cache: "no-store",
      signal: AbortSignal.timeout(90_000),
    });
  } catch {
    return jsonError("Cannot reach the report service. Start it on port 8001.", 502);
  }

  const responseText = await upstream.text();
  let responseBody: unknown;
  try {
    responseBody = JSON.parse(responseText);
  } catch {
    return jsonError("The report service returned invalid JSON.", 502);
  }
  if (!isRecord(responseBody) && !Array.isArray(responseBody)) {
    return jsonError("The report service returned an unexpected response.", 502);
  }

  if (!upstream.ok) {
    const detail = isRecord(responseBody) && typeof responseBody.detail === "string"
      ? responseBody.detail
      : "Report service request failed.";
    return jsonError(detail, upstream.status);
  }
  return Response.json(responseBody, {
    status: upstream.status,
    headers: { "Cache-Control": "no-store" },
  });
}

export async function GET(request: Request) {
  if (!getAuthorization(request)) {
    return jsonError("Sign in to mission control before using reports.", 401);
  }
  const resource = new URL(request.url).searchParams.get("resource");
  if (resource !== "health" && resource !== "scenarios") {
    return jsonError("Request a valid report resource.", 400);
  }
  const path = resource === "health" ? "/api/report/health/" : "/api/report/scenarios/";
  return proxyReport(path, { headers: { Accept: "application/json" } });
}

export async function POST(request: Request) {
  const authorization = getAuthorization(request);
  if (!authorization) {
    return jsonError("Sign in to mission control before generating a report.", 401);
  }

  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return jsonError("Report request is too large.", 413);
  }
  const bodyText = await request.text();
  if (new TextEncoder().encode(bodyText).byteLength > MAX_BODY_BYTES) {
    return jsonError("Report request is too large.", 413);
  }

  let payload: unknown;
  try {
    payload = JSON.parse(bodyText);
  } catch {
    return jsonError("Request body must be valid JSON.", 400);
  }
  if (!isRecord(payload)) {
    return jsonError("Request body must be a JSON object.", 400);
  }

  const profileId = payload.profile_id;
  const scenario = payload.scenario;
  const missionDay = payload.mission_day;
  if (payload.consent !== true) {
    return jsonError("Confirm consent before sending a synthetic report request to Gemini.", 400);
  }
  if (typeof profileId !== "string" || !profileId.trim() || profileId.length > 128) {
    return jsonError("Select a valid crew profile first.", 400);
  }
  if (typeof scenario !== "string" || !SCENARIOS.has(scenario)) {
    return jsonError("Select a supported report scenario.", 400);
  }
  if (
    missionDay !== null &&
    missionDay !== undefined &&
    (
      typeof missionDay !== "number" ||
      !Number.isInteger(missionDay) ||
      missionDay < 1 ||
      missionDay > 3650
    )
  ) {
    return jsonError("Mission day must be an integer between 1 and 3650.", 400);
  }

  let profilesResponse: Response;
  try {
    profilesResponse = await fetch(`${MISSION_API_URL}/api/v1/profiles/`, {
      headers: { Authorization: authorization, Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
  } catch {
    return jsonError("Cannot verify the selected profile with the mission API.", 502);
  }
  if (profilesResponse.status === 401) {
    return jsonError("Your mission API session expired. Sign in again.", 401);
  }
  if (!profilesResponse.ok) {
    return jsonError("Could not verify access to the selected crew profile.", 502);
  }

  let profilesBody: unknown;
  try {
    profilesBody = await profilesResponse.json();
  } catch {
    return jsonError("The mission API returned invalid profile data.", 502);
  }
  if (!Array.isArray(profilesBody)) {
    return jsonError("The mission API returned an unexpected profile list.", 502);
  }
  const profile = profilesBody.find(
    (item): item is CrewProfile => isCrewProfile(item) && item.profile_id === profileId,
  );
  if (!profile) {
    return jsonError("This account cannot access the selected crew profile.", 403);
  }

  const reportRequest = {
    astronaut_name: profile.display_name,
    profile_id: profile.profile_id,
    mission_name: profile.mission_name,
    mission_day: missionDay ?? null,
    mission_phase: profile.mission_phase,
    scenario,
  };
  return proxyReport("/api/report/generate/", {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(reportRequest),
  });
}
