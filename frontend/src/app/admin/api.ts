// API functions for admin page

export interface ClientControl {
  client_name: string;
  enabled: boolean;
  disabled_at: string | null;
  disabled_by: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface BlockedRequest {
  timestamp: string;
  client_name: string | null;
  source_path: string | null;
  block_reason: string;
  endpoint: string;
}

export async function fetchClients(): Promise<ClientControl[]> {
  const res = await fetch("/api/admin/clients");
  const data = await res.json();
  return data.clients || [];
}

export async function fetchBlockedRequests(): Promise<BlockedRequest[]> {
  const res = await fetch("/api/admin/blocked-requests?limit=1000");
  const data = await res.json();
  return data.requests || [];
}

export async function disableClient(clientName: string, reason: string, disabledBy: string): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, disabled_by: disabledBy }),
  });
}

export async function enableClient(clientName: string): Promise<void> {
  await fetch(`/api/admin/clients/${clientName}/disable`, { method: "DELETE" });
}
