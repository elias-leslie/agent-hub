"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Shield, Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";
import { buildApiUrl, fetchApi } from "@/lib/api-config";

interface ClientCreateResponse {
  client_id: string;
  display_name: string;
  secret: string;
  secret_prefix: string;
  client_type: string;
  status: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  created_at: string;
  message: string;
}

export default function NewClientPage() {
  const router = useRouter();
  const [displayName, setDisplayName] = useState("");
  const [clientType, setClientType] = useState("external");
  const [rateLimitRpm, setRateLimitRpm] = useState(60);
  const [rateLimitTpm, setRateLimitTpm] = useState(100000);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createdClient, setCreatedClient] = useState<ClientCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetchApi(buildApiUrl("/api/access-control/clients"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          display_name: displayName,
          client_type: clientType,
          rate_limit_rpm: rateLimitRpm,
          rate_limit_tpm: rateLimitTpm,
        }),
      });

      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.detail || "Failed to create client");
      }

      const data: ClientCreateResponse = await response.json();
      setCreatedClient(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

  function handleCopySecret() {
    if (createdClient?.secret) {
      navigator.clipboard.writeText(createdClient.secret);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  }

  if (createdClient) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
        <div className="max-w-lg w-full bg-slate-900/80 border border-slate-800 rounded-xl p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="p-2 rounded-lg bg-emerald-500/10">
              <Shield className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-100">Client Created</h1>
              <p className="text-sm text-slate-400">{createdClient.display_name}</p>
            </div>
          </div>

          <div className="bg-amber-900/20 border border-amber-800/50 rounded-lg p-4 mb-6">
            <p className="text-sm text-amber-300 mb-2 font-medium">
              Save this secret now - it will not be shown again!
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 p-3 bg-slate-950 rounded font-mono text-sm text-slate-100 break-all">
                {createdClient.secret}
              </code>
              <button
                onClick={handleCopySecret}
                className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition-colors"
              >
                {copied ? (
                  <Check className="h-5 w-5 text-emerald-400" />
                ) : (
                  <Copy className="h-5 w-5 text-slate-400" />
                )}
              </button>
            </div>
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Client ID</span>
              <code className="text-slate-100 font-mono">{createdClient.client_id}</code>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Type</span>
              <span className="text-slate-100 capitalize">{createdClient.client_type}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Rate Limits</span>
              <span className="text-slate-100 font-mono">
                {createdClient.rate_limit_rpm} rpm / {(createdClient.rate_limit_tpm / 1000).toFixed(0)}k tpm
              </span>
            </div>
          </div>

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => router.push("/access-control/clients")}
              className="flex-1 py-2 px-4 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm font-medium transition-colors"
            >
              View All Clients
            </button>
            <button
              onClick={() => {
                setCreatedClient(null);
                setDisplayName("");
              }}
              className="flex-1 py-2 px-4 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors"
            >
              Create Another
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center">
          <Shield className="h-5 w-5 text-slate-400 mr-3" />
          <h1 className="text-base font-semibold text-slate-100">Register New Client</h1>
        </div>
      </header>

      <main className="relative max-w-xl mx-auto px-6 py-8">
        <form onSubmit={handleSubmit} className="space-y-6">
          {error && (
            <div className="p-3 rounded-lg bg-red-900/20 border border-red-800/50">
              <p className="text-sm text-red-400">{error}</p>
            </div>
          )}

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Display Name
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="My API Client"
              required
              minLength={1}
              maxLength={100}
              className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              Client Type
            </label>
            <select
              value={clientType}
              onChange={(e) => setClientType(e.target.value)}
              className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
            >
              <option value="external">External</option>
              <option value="internal">Internal</option>
              <option value="service">Service</option>
            </select>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Rate Limit (RPM)
              </label>
              <input
                type="number"
                value={rateLimitRpm}
                onChange={(e) => setRateLimitRpm(parseInt(e.target.value) || 60)}
                min={1}
                max={10000}
                className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Rate Limit (TPM)
              </label>
              <input
                type="number"
                value={rateLimitTpm}
                onChange={(e) => setRateLimitTpm(parseInt(e.target.value) || 100000)}
                min={1000}
                max={10000000}
                className="w-full px-4 py-2 rounded-lg bg-slate-800 border border-slate-700 text-slate-100 focus:outline-none focus:border-blue-500"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={isSubmitting || !displayName.trim()}
            className={cn(
              "w-full py-3 px-4 rounded-lg text-white font-medium transition-colors",
              isSubmitting || !displayName.trim()
                ? "bg-slate-700 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-500"
            )}
          >
            {isSubmitting ? "Creating..." : "Create Client"}
          </button>
        </form>
      </main>
    </div>
  );
}
