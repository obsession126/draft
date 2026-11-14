const CHATBOT_API_URL = process.env.CHATBOT_API_URL ?? "http://127.0.0.1:8766";
const MAX_BODY_BYTES = 64 * 1024;
const MAX_MESSAGE_LENGTH = 2_000;

function jsonError(message: string, status: number) {
  return Response.json({ error: message }, { status });
}

export async function POST(request: Request) {
  const authorization = request.headers.get("authorization");
  if (!authorization || !/^Token\s+\S+$/.test(authorization)) {
    return jsonError("Sign in to the mission API to continue.", 401);
  }

  const contentLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return jsonError("Chat request is too large.", 413);
  }

  const bodyText = await request.text();
  if (new TextEncoder().encode(bodyText).byteLength > MAX_BODY_BYTES) {
    return jsonError("Chat request is too large.", 413);
  }

  let payload: unknown;
  try {
    payload = JSON.parse(bodyText);
  } catch {
    return jsonError("Request body must be valid JSON.", 400);
  }

  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return jsonError("Request body must be a JSON object.", 400);
  }
  const requestBody = payload as Record<string, unknown>;
  if (
    typeof requestBody.profile_id !== "string" ||
    !requestBody.profile_id.trim() ||
    requestBody.profile_id.length > 128
  ) {
    return jsonError("Select a valid crew profile first.", 400);
  }
  if (
    typeof requestBody.message !== "string" ||
    !requestBody.message.trim() ||
    requestBody.message.length > MAX_MESSAGE_LENGTH
  ) {
    return jsonError(`Question must be between 1 and ${MAX_MESSAGE_LENGTH} characters.`, 400);
  }
  if (requestBody.history !== undefined && !Array.isArray(requestBody.history)) {
    return jsonError("Conversation history must be a list.", 400);
  }

  let endpoint: URL;
  try {
    endpoint = new URL("/api/chat", CHATBOT_API_URL);
    if (!["http:", "https:"].includes(endpoint.protocol)) {
      return jsonError("CHATBOT_API_URL must use HTTP or HTTPS.", 500);
    }
  } catch {
    return jsonError("CHATBOT_API_URL must be a valid HTTP(S) URL.", 500);
  }

  let upstream: Response;
  try {
    upstream = await fetch(endpoint, {
      method: "POST",
      headers: {
        Authorization: authorization,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(requestBody),
      cache: "no-store",
      signal: AbortSignal.timeout(60_000),
    });
  } catch {
    return jsonError(
      "Cannot reach the chatbot service. Start it with GEMINI_API_KEY configured.",
      502,
    );
  }

  const responseText = await upstream.text();
  let responseBody: unknown;
  try {
    responseBody = JSON.parse(responseText);
  } catch {
    return jsonError("The chatbot service returned invalid JSON.", 502);
  }
  if (!responseBody || typeof responseBody !== "object" || Array.isArray(responseBody)) {
    return jsonError("The chatbot service returned an unexpected response.", 502);
  }
  return Response.json(responseBody, {
    status: upstream.status,
    headers: { "Cache-Control": "no-store" },
  });
}
