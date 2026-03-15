export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const AGENT_HUB_API_URL =
  process.env.AGENT_HUB_API_URL || "http://localhost:8003";
const BACKEND_URL = `${AGENT_HUB_API_URL}/api/memory/capture/stream`;
const CLIENT_ID = process.env.AGENT_HUB_DASHBOARD_CLIENT_ID || "";
const REQUEST_SOURCE =
  process.env.AGENT_HUB_DASHBOARD_REQUEST_SOURCE || "agent-hub-dashboard";

export async function GET(): Promise<Response> {
  const headers: Record<string, string> = { Accept: "text/event-stream" };
  if (CLIENT_ID) headers["X-Client-Id"] = CLIENT_ID;
  if (REQUEST_SOURCE) headers["X-Request-Source"] = REQUEST_SOURCE;

  const upstream = await fetch(BACKEND_URL, {
    headers,
    cache: "no-store",
  });

  if (!upstream.ok || !upstream.body) {
    return new Response("SSE upstream unavailable", { status: 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
