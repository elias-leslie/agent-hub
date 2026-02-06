export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const BACKEND_URL = "http://localhost:8003/api/memory/capture/stream";

export async function GET(): Promise<Response> {
  const upstream = await fetch(BACKEND_URL, {
    headers: { Accept: "text/event-stream" },
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
