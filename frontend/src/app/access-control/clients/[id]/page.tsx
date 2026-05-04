'use client'

import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Shield } from 'lucide-react'
import { useParams, useRouter } from 'next/navigation'
import { useState } from 'react'
import { buildApiUrl, fetchApi } from '@/lib/api-config'
import { cn } from '@/lib/utils'
import { ActionButtons } from './components/ActionButtons'
import { ClientDetailsCard } from './components/ClientDetailsCard'
import { ConfirmationModal } from './components/ConfirmationModal'
import { EditClientModal } from './components/EditClientModal'
import { useClientMutations } from './hooks/useClientMutations'

interface ClientResponse {
  client_id: string
  display_name: string
  client_type: string
  status: string
  rate_limit_rpm: number
  rate_limit_tpm: number
  allowed_projects: string[] | null
  created_at: string
  updated_at: string
  last_used_at: string | null
  suspended_at: string | null
  suspended_by: string | null
  suspension_reason: string | null
}

interface ClientUpdateRequest {
  display_name?: string
  rate_limit_rpm?: number
  rate_limit_tpm?: number
  allowed_projects?: string[]
}

async function fetchClient(clientId: string): Promise<ClientResponse> {
  const response = await fetchApi(
    buildApiUrl(`/api/access-control/clients/${clientId}`),
  )
  if (!response.ok) {
    throw new Error(`Failed to fetch client: ${response.statusText}`)
  }
  return response.json()
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return 'Never'
  return new Date(dateStr).toLocaleString()
}

export default function ClientDetailPage() {
  const params = useParams()
  const router = useRouter()
  const clientId = params.id as string

  const [showSuspendModal, setShowSuspendModal] = useState(false)
  const [showBlockModal, setShowBlockModal] = useState(false)
  const [showEditModal, setShowEditModal] = useState(false)

  const {
    data: client,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['access-control-client', clientId],
    queryFn: () => fetchClient(clientId),
    refetchInterval: 10000,
  })

  const { suspendMutation, activateMutation, blockMutation, updateMutation } =
    useClientMutations(clientId)

  function handleSuspend(reason: string) {
    suspendMutation.mutate(reason, {
      onSuccess: () => setShowSuspendModal(false),
    })
  }

  function handleBlock(reason: string) {
    blockMutation.mutate(reason, {
      onSuccess: () => setShowBlockModal(false),
    })
  }

  function handleUpdate(updates: ClientUpdateRequest) {
    updateMutation.mutate(updates, {
      onSuccess: () => setShowEditModal(false),
    })
  }

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-slate-800/60 border-t-amber-500 rounded-full" />
      </div>
    )
  }

  if (error || !client) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-center">
          <p className="text-red-400 mb-4">Failed to load client</p>
          <button
            onClick={() => router.push('/access-control/clients')}
            className="text-amber-400 hover:text-amber-300"
          >
            Back to clients
          </button>
        </div>
      </div>
    )
  }

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
  const config =
    statusConfig[client.status as keyof typeof statusConfig] ||
    statusConfig.active

  return (
    <div className="page-shell">
      <div className="page-backdrop" />

      <header className="page-header">
        <div className="page-container px-4 lg:px-8">
          <div className="page-header-row">
            <div className="page-title-group">
              <button
                onClick={() => router.push('/access-control/clients')}
                className="icon-button"
                aria-label="Go back"
              >
                <ArrowLeft className="h-5 w-5" />
              </button>
              <div className="page-title-icon">
                <Shield className="h-5 w-5" />
              </div>
              <div className="page-title-stack">
                <div className="flex flex-wrap items-center gap-2">
                  <h1 className="page-title">{client.display_name}</h1>
                  <span className={cn('page-pill', config.bg, config.color)}>
                    {config.label}
                  </span>
                </div>
                <div className="page-meta">
                  <span className="page-pill capitalize">
                    {client.client_type}
                  </span>
                  <span className="page-pill font-mono">
                    {client.client_id.slice(0, 12)}...
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="page-container">
        <div className="page-frame">
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_23rem]">
            <ClientDetailsCard
              client={client}
              formatDate={formatDate}
              statusConfig={config}
            />

            <div className="space-y-6">
              <ActionButtons
                clientStatus={client.status}
                onEdit={() => setShowEditModal(true)}
                onSuspend={() => setShowSuspendModal(true)}
                onActivate={() => activateMutation.mutate()}
                onBlock={() => setShowBlockModal(true)}
                isActivating={activateMutation.isPending}
              />
              <section className="panel-surface p-5 lg:p-6">
                <p className="section-kicker">Request Budget</p>
                <h2 className="section-heading mt-2">Throttle Snapshot</h2>
                <div className="mt-5 detail-grid">
                  <div className="detail-card">
                    <p className="detail-label">RPM</p>
                    <p className="detail-value font-mono">
                      {client.rate_limit_rpm}
                    </p>
                  </div>
                  <div className="detail-card">
                    <p className="detail-label">TPM</p>
                    <p className="detail-value font-mono">
                      {client.rate_limit_tpm.toLocaleString()}
                    </p>
                  </div>
                </div>
              </section>
            </div>
          </div>
        </div>
      </main>

      <ConfirmationModal
        isOpen={showSuspendModal}
        onClose={() => setShowSuspendModal(false)}
        onConfirm={handleSuspend}
        title="Suspend Client"
        description="The client will be temporarily blocked. You can reactivate it later."
        confirmText="Suspend"
        confirmClassName="bg-amber-600 hover:bg-amber-500"
        isPending={suspendMutation.isPending}
      />

      <ConfirmationModal
        isOpen={showBlockModal}
        onClose={() => setShowBlockModal(false)}
        onConfirm={handleBlock}
        title="Block Client Permanently"
        description="This action cannot be undone. The client will be permanently blocked."
        confirmText="Block Permanently"
        confirmClassName="bg-red-600 hover:bg-red-500"
        isPending={blockMutation.isPending}
        isDanger
      />

      <EditClientModal
        client={client}
        isOpen={showEditModal}
        onClose={() => setShowEditModal(false)}
        onUpdate={handleUpdate}
        isPending={updateMutation.isPending}
      />
    </div>
  )
}
