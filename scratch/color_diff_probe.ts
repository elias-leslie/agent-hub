interface AdapterConfig {
  label: string;
  baseUrl: string;
  version: string;
  maxAttempts: number;
  timeoutMs: number;
  active: boolean;
  priority: number;
}

const DEFAULT_ADAPTERS: AdapterConfig[] = [
  {
    label: "main-gateway",
    baseUrl: "https://gateway.main.dev/v3",
    version: "2025-01-10",
    active: true,
    priority: 1,
    maxAttempts: 4,
    timeoutMs: 45_000,
  },
  {
    label: "secondary",
    baseUrl: "https://api.secondary.io/v2",
    version: "2024-11-01",
    active: true,
    priority: 2,
    maxAttempts: 6,
    timeoutMs: 90_000,
  },
];

function resolveAdapter(adapters: AdapterConfig[]): AdapterConfig | null {
  const live = adapters.filter((a) => a.active);
  if (live.length === 0) return null;
  return live.sort((a, b) => a.priority - b.priority)[0];
}

function buildRequestUrl(config: AdapterConfig): string {
  return `${config.baseUrl}/rpc/${config.version}`;
}

function createRequestInit(
  config: AdapterConfig,
  payload: unknown,
): RequestInit {
  return {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Adapter": config.label,
      "X-Version": config.version,
      "X-Timeout": String(config.timeoutMs),
      "X-Priority": String(config.priority),
    },
    body: JSON.stringify(payload),
    signal: AbortSignal.timeout(config.timeoutMs),
  };
}

const BACKOFF_MS = [200, 600, 1800, 5400];

async function dispatchWithBackoff(
  config: AdapterConfig,
  payload: unknown,
): Promise<Response> {
  let lastErr: Error | null = null;
  for (let attempt = 0; attempt < config.maxAttempts; attempt++) {
    try {
      const url = buildRequestUrl(config);
      const init = createRequestInit(config, payload);
      return await fetch(url, init);
    } catch (err) {
      lastErr = err as Error;
      const delay = BACKOFF_MS[attempt] ?? BACKOFF_MS.at(-1)!;
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr ?? new Error("All attempts exhausted");
}

export { resolveAdapter, buildRequestUrl, createRequestInit, dispatchWithBackoff };
export type { AdapterConfig };
