'use client'

import { ArrowLeft, Check, Copy, Shield } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'
import { buildApiUrl, fetchApi } from '@/lib/api-config'
import { cn } from '@/lib/utils'

interface ClientCreateResponse {
  client_id: string
  display_name: string
  client_type: string
  status: string
  rate_limit_rpm: number
  rate_limit_tpm: number
  created_at: string
}

export default function NewClientPage() {
  const router = useRouter()
  const [displayName, setDisplayName] = useState('')
  const [clientType, setClientType] = useState('external')
  const [rateLimitRpm, setRateLimitRpm] = useState(60)
  const [rateLimitTpm, setRateLimitTpm] = useState(100000)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdClient, setCreatedClient] =
    useState<ClientCreateResponse | null>(null)
  const [copiedId, setCopiedId] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setIsSubmitting(true)
    setError(null)

    try {
      const response = await fetchApi(
        buildApiUrl('/api/access-control/clients'),
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            display_name: displayName,
            client_type: clientType,
            rate_limit_rpm: rateLimitRpm,
            rate_limit_tpm: rateLimitTpm,
          }),
        },
      )

      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail || 'Failed to create client')
      }

      const data: ClientCreateResponse = await response.json()
      setCreatedClient(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'An error occurred')
    } finally {
      setIsSubmitting(false)
    }
  }

  function handleCopyId() {
    if (createdClient?.client_id) {
      navigator.clipboard.writeText(createdClient.client_id)
      setCopiedId(true)
      setTimeout(() => setCopiedId(false), 2000)
    }
  }

  if (createdClient) {
    return (
      <div className="page-shell flex items-center justify-center p-6">
        <div className="page-backdrop" />
        <div className="panel-surface max-w-lg w-full p-6">
          <div className="flex items-center gap-3 mb-6">
            <div className="page-title-icon border-emerald-500/20 bg-emerald-500/10 text-emerald-200">
              <Shield className="h-6 w-6 text-emerald-400" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-slate-100">
                Client Created
              </h1>
              <p className="text-sm text-slate-400">
                {createdClient.display_name}
              </p>
            </div>
          </div>

          <div className="bg-amber-900/20 border border-amber-800/50 rounded-lg p-4 mb-6">
            <p className="text-sm text-amber-300 mb-2 font-medium">
              Client ID (use in X-Client-Id header)
            </p>
            <div className="flex items-center gap-2">
              <code className="flex-1 p-3 bg-slate-950 rounded font-mono text-sm text-slate-100 break-all">
                {createdClient.client_id}
              </code>
              <button
                onClick={handleCopyId}
                className="p-2 rounded bg-slate-800 hover:bg-slate-700 transition-colors"
              >
                {copiedId ? (
                  <Check className="h-5 w-5 text-emerald-400" />
                ) : (
                  <Copy className="h-5 w-5 text-slate-400" />
                )}
              </button>
            </div>
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex justify-between">
              <span className="text-slate-400">Type</span>
              <span className="text-slate-100 capitalize">
                {createdClient.client_type}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Rate Limits</span>
              <span className="text-slate-100 font-mono">
                {createdClient.rate_limit_rpm} rpm /{' '}
                {(createdClient.rate_limit_tpm / 1000).toFixed(0)}k tpm
              </span>
            </div>
          </div>

          <div className="mt-6 flex gap-3">
            <button
              onClick={() => router.push('/access-control/clients')}
              className="button-secondary flex-1 justify-center"
            >
              View All Clients
            </button>
            <button
              onClick={() => {
                setCreatedClient(null)
                setDisplayName('')
              }}
              className="button-primary flex-1 justify-center"
            >
              Create Another
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="page-shell">
      <div className="page-backdrop" />

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <Link
                href="/access-control/clients"
                className="icon-button"
                aria-label="Go back"
              >
                <ArrowLeft className="h-5 w-5" />
              </Link>
              <div className="page-title-icon">
                <Shield className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <h1 className="page-title">Register New Client</h1>
                <p className="page-subtitle">
                  Create a caller identity with a display name, type, and
                  throttle policy.
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="page-container">
        <div className="page-frame">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
            <form
              onSubmit={handleSubmit}
              className="panel-surface space-y-6 p-5 lg:p-6"
            >
              {error && (
                <div className="rounded-2xl border border-red-800/50 bg-red-900/20 p-3">
                  <p className="text-sm text-red-400">{error}</p>
                </div>
              )}

              <div>
                <p className="section-kicker">Client Identity</p>
                <h2 className="section-heading mt-2">Core Details</h2>
              </div>

              <div>
                <label className="detail-label mb-2 block">Display Name</label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder="My API Client"
                  required
                  minLength={1}
                  maxLength={100}
                  className="control-input"
                />
                <p className="mt-2 text-xs text-slate-400">
                  Use a descriptive label operators can recognize quickly in
                  access-control lists.
                </p>
              </div>

              <div>
                <label className="detail-label mb-2 block">Client Type</label>
                <select
                  value={clientType}
                  onChange={(e) => setClientType(e.target.value)}
                  className="control-select w-full"
                >
                  <option value="external">External</option>
                  <option value="internal">Internal</option>
                  <option value="service">Service</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="detail-label mb-2 block">
                    Rate Limit (RPM)
                  </label>
                  <input
                    type="number"
                    value={rateLimitRpm}
                    onChange={(e) =>
                      setRateLimitRpm(parseInt(e.target.value, 10) || 60)
                    }
                    min={1}
                    max={10000}
                    className="control-input"
                  />
                </div>
                <div>
                  <label className="detail-label mb-2 block">
                    Rate Limit (TPM)
                  </label>
                  <input
                    type="number"
                    value={rateLimitTpm}
                    onChange={(e) =>
                      setRateLimitTpm(parseInt(e.target.value, 10) || 100000)
                    }
                    min={1000}
                    max={10000000}
                    className="control-input"
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={isSubmitting || !displayName.trim()}
                className={cn(
                  'button-primary w-full justify-center',
                  isSubmitting || !displayName.trim()
                    ? 'cursor-not-allowed border-slate-700 bg-slate-800 text-slate-500 shadow-none'
                    : '',
                )}
              >
                {isSubmitting ? 'Creating...' : 'Create Client'}
              </button>
            </form>
            <aside className="panel-surface p-5 lg:p-6">
              <p className="section-kicker">Provisioning Notes</p>
              <h2 className="section-heading mt-2">Policy Guide</h2>
              <div className="mt-5 space-y-3">
                <div className="detail-card">
                  <p className="detail-label">External</p>
                  <p className="detail-value">
                    Use for third-party callers and partner integrations.
                  </p>
                </div>
                <div className="detail-card">
                  <p className="detail-label">Internal</p>
                  <p className="detail-value">
                    Use for first-party dashboards and trusted internal tooling.
                  </p>
                </div>
                <div className="detail-card">
                  <p className="detail-label">Service</p>
                  <p className="detail-value">
                    Use for background workers, automation, and server-to-server
                    jobs.
                  </p>
                </div>
              </div>
            </aside>
          </div>
        </div>
      </main>
    </div>
  )
}
