'use client'

import { useQuery } from '@tanstack/react-query'
import { Layers, Plus, Shield, Users } from 'lucide-react'
import Link from 'next/link'
import { buildApiUrl, fetchApi } from '@/lib/api-config'
import { formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'

interface ClientResponse {
  client_id: string
  display_name: string
  client_type: string
  status: string
  rate_limit_rpm: number
  rate_limit_tpm: number
  created_at: string
  updated_at: string
  last_used_at: string | null
}

interface ClientListResponse {
  clients: ClientResponse[]
  total: number
}

async function fetchClients(): Promise<ClientListResponse> {
  const response = await fetchApi(buildApiUrl('/api/access-control/clients'))
  if (!response.ok) {
    throw new Error(`Failed to fetch clients: ${response.statusText}`)
  }
  return response.json()
}

export default function ClientsPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['access-control-clients'],
    queryFn: fetchClients,
    refetchInterval: 30000,
  })

  const statusConfig = {
    active: {
      color: 'text-emerald-400',
      bg: 'bg-emerald-500/10',
      label: 'Active',
    },
    suspended: {
      color: 'text-amber-400',
      bg: 'bg-amber-500/10',
      label: 'Suspended',
    },
    blocked: { color: 'text-red-400', bg: 'bg-red-500/10', label: 'Blocked' },
  }
  const clients = data?.clients ?? []
  const activeCount = clients.filter(
    (client) => client.status === 'active',
  ).length
  const serviceCount = clients.filter(
    (client) => client.client_type === 'service',
  ).length
  const internalCount = clients.filter(
    (client) => client.client_type === 'internal',
  ).length

  return (
    <div className="page-shell">
      <div className="page-backdrop" />

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <div className="page-title-icon">
                <Users className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">Clients</h1>
                  <span className="page-pill">
                    {data?.total ?? 0} registered
                  </span>
                </div>
                <p className="page-subtitle">
                  Manage authenticated client identities, throttles, and project
                  access.
                </p>
              </div>
            </div>
            <div className="page-toolbar">
              <Link
                href="/access-control/clients/new"
                className="button-primary"
              >
                <Plus className="h-4 w-4" />
                New Client
              </Link>
            </div>
          </div>
        </div>
      </header>

      <main className="page-container">
        <div className="page-frame space-y-6">
          <section className="detail-grid">
            <article className="detail-card animate-fade-up">
              <p className="detail-label">Active Clients</p>
              <p className="detail-value text-2xl font-semibold text-slate-50">
                {activeCount}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                Ready to make authenticated requests.
              </p>
            </article>
            <article className="detail-card animate-fade-up stagger-1">
              <p className="detail-label">Service Clients</p>
              <p className="detail-value text-2xl font-semibold text-slate-50">
                {serviceCount}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                Machine-to-machine callers and automation.
              </p>
            </article>
            <article className="detail-card animate-fade-up stagger-2">
              <p className="detail-label">Internal Clients</p>
              <p className="detail-value text-2xl font-semibold text-slate-50">
                {internalCount}
              </p>
              <p className="mt-1 text-sm text-slate-400">
                First-party dashboards and internal tooling.
              </p>
            </article>
          </section>

          {error && (
            <div className="rounded-2xl border border-red-800/50 bg-red-900/20 p-3">
              <p className="text-sm text-red-400">Failed to load clients</p>
            </div>
          )}

          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-24 rounded-2xl animate-shimmer" />
              ))}
            </div>
          ) : data?.clients.length === 0 ? (
            <div className="empty-surface flex flex-col items-center justify-center text-slate-400">
              <Users className="h-12 w-12 mb-4 opacity-50" />
              <p className="text-lg mb-2">No clients registered</p>
              <Link
                href="/access-control/clients/new"
                className="text-amber-300 hover:text-amber-200"
              >
                Register your first client
              </Link>
            </div>
          ) : (
            <div className="table-surface animate-fade-up stagger-3">
              <table className="w-full">
                <thead className="bg-slate-900/80">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Client
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Type
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Last Used
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Rate Limits
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {data?.clients.map((client) => {
                    const config =
                      statusConfig[
                        client.status as keyof typeof statusConfig
                      ] || statusConfig.active
                    return (
                      <tr
                        key={client.client_id}
                        className="cursor-pointer transition hover:bg-slate-800/30"
                        onClick={() => {
                          window.location.href = `/access-control/clients/${client.client_id}`
                        }}
                        onKeyDown={(event) => {
                          if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault()
                            window.location.href = `/access-control/clients/${client.client_id}`
                          }
                        }}
                        tabIndex={0}
                      >
                        <td className="px-4 py-3">
                          <div>
                            <p className="text-sm font-medium text-slate-100">
                              {client.display_name}
                            </p>
                            <p className="text-xs text-slate-500 font-mono">
                              {client.client_id.slice(0, 8)}...
                            </p>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex items-center gap-1 rounded-full border border-slate-700/80 bg-slate-900/80 px-2.5 py-1 text-xs text-slate-300 capitalize">
                            {client.client_type === 'service' ? (
                              <Layers className="h-3 w-3" />
                            ) : (
                              <Shield className="h-3 w-3" />
                            )}
                            {client.client_type}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={cn(
                              'inline-flex rounded-full px-2.5 py-1 text-xs font-medium',
                              config.bg,
                              config.color,
                            )}
                          >
                            {config.label}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-400">
                          {formatRelativeTime(client.last_used_at)}
                        </td>
                        <td className="px-4 py-3 text-xs text-slate-500 font-mono">
                          {client.rate_limit_rpm} rpm /{' '}
                          {(client.rate_limit_tpm / 1000).toFixed(0)}k tpm
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
