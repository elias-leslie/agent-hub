import { cn } from '@/lib/utils'

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

interface ClientDetailsCardProps {
  client: ClientResponse
  formatDate: (date: string | null) => string
  statusConfig: {
    color: string
    bg: string
    label: string
  }
}

export function ClientDetailsCard({
  client,
  formatDate,
  statusConfig,
}: ClientDetailsCardProps) {
  return (
    <section className="panel-surface p-5 lg:p-6">
      <div className="section-header gap-4">
        <div>
          <p className="section-kicker">Authentication Profile</p>
          <h2 className="section-heading mt-2">Client Details</h2>
          <p className="section-copy mt-2">
            Review identity, project scope, and throttle limits for this caller.
          </p>
        </div>
      </div>

      <div className="detail-grid mt-5">
        <div className="detail-card md:col-span-2 xl:col-span-3">
          <p className="detail-label">Client ID</p>
          <p className="detail-value font-mono break-all">{client.client_id}</p>
        </div>
        <div className="detail-card">
          <p className="detail-label">Type</p>
          <p className="detail-value capitalize">{client.client_type}</p>
        </div>
        <div className="detail-card">
          <p className="detail-label">Status</p>
          <p className={cn('detail-value capitalize', statusConfig.color)}>
            {client.status}
          </p>
        </div>
        <div className="detail-card">
          <p className="detail-label">Rate Limit</p>
          <p className="detail-value font-mono">{client.rate_limit_rpm} rpm</p>
          <p className="mt-1 text-xs text-slate-500">
            {client.rate_limit_tpm.toLocaleString()} tpm
          </p>
        </div>
        <div className="detail-card md:col-span-2 xl:col-span-3">
          <p className="detail-label">Allowed Projects</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {client.allowed_projects === null ? (
              <span className="page-pill border-emerald-500/20 bg-emerald-500/10 text-emerald-200">
                Unrestricted
              </span>
            ) : client.allowed_projects.length === 0 ? (
              <span className="page-pill border-rose-500/20 bg-rose-500/10 text-rose-200">
                No projects allowed
              </span>
            ) : (
              client.allowed_projects.map((project) => (
                <span key={project} className="page-pill font-mono">
                  {project}
                </span>
              ))
            )}
          </div>
        </div>
        <div className="detail-card">
          <p className="detail-label">Created</p>
          <p className="detail-value">{formatDate(client.created_at)}</p>
        </div>
        <div className="detail-card">
          <p className="detail-label">Updated</p>
          <p className="detail-value">{formatDate(client.updated_at)}</p>
        </div>
        <div className="detail-card">
          <p className="detail-label">Last Used</p>
          <p className="detail-value">{formatDate(client.last_used_at)}</p>
        </div>
      </div>

      {client.suspension_reason && (
        <div className="mt-5 rounded-2xl border border-amber-500/20 bg-amber-500/10 px-4 py-4">
          <span className="detail-label">Suspension Reason</span>
          <p className="mt-2 text-amber-100">{client.suspension_reason}</p>
          {client.suspended_at && (
            <p className="mt-2 text-xs text-amber-200/80">
              {client.status === 'blocked' ? 'Blocked' : 'Suspended'} at{' '}
              {formatDate(client.suspended_at)}
              {client.suspended_by && ` by ${client.suspended_by}`}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
