import { cn } from "@/lib/utils";

interface ClientResponse {
  client_id: string;
  display_name: string;
  secret_prefix: string;
  client_type: string;
  status: string;
  rate_limit_rpm: number;
  rate_limit_tpm: number;
  allowed_projects: string[] | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
  suspended_at: string | null;
  suspended_by: string | null;
  suspension_reason: string | null;
}

interface ClientDetailsCardProps {
  client: ClientResponse;
  formatDate: (date: string | null) => string;
  statusConfig: {
    color: string;
    bg: string;
    label: string;
  };
}

export function ClientDetailsCard({ client, formatDate, statusConfig }: ClientDetailsCardProps) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6 mb-6">
      <h2 className="text-sm font-semibold text-slate-300 mb-4">Client Details</h2>
      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-slate-400">Client ID</span>
          <p className="text-slate-100 font-mono mt-1">{client.client_id}</p>
        </div>
        <div>
          <span className="text-slate-400">Secret Prefix</span>
          <p className="text-slate-100 font-mono mt-1">{client.secret_prefix}...</p>
        </div>
        <div>
          <span className="text-slate-400">Type</span>
          <p className="text-slate-100 capitalize mt-1">{client.client_type}</p>
        </div>
        <div>
          <span className="text-slate-400">Status</span>
          <p className={cn("mt-1 capitalize", statusConfig.color)}>{client.status}</p>
        </div>
        <div>
          <span className="text-slate-400">Rate Limit (RPM)</span>
          <p className="text-slate-100 font-mono mt-1">{client.rate_limit_rpm}</p>
        </div>
        <div>
          <span className="text-slate-400">Rate Limit (TPM)</span>
          <p className="text-slate-100 font-mono mt-1">{client.rate_limit_tpm.toLocaleString()}</p>
        </div>
        <div className="col-span-2">
          <span className="text-slate-400">Allowed Projects</span>
          <p className="text-slate-100 mt-1">
            {client.allowed_projects === null ? (
              <span className="text-emerald-400">Unrestricted (all projects)</span>
            ) : client.allowed_projects.length === 0 ? (
              <span className="text-red-400">No projects allowed</span>
            ) : (
              <span className="font-mono text-sm">
                {client.allowed_projects.join(", ")}
              </span>
            )}
          </p>
        </div>
        <div>
          <span className="text-slate-400">Created</span>
          <p className="text-slate-100 mt-1">{formatDate(client.created_at)}</p>
        </div>
        <div>
          <span className="text-slate-400">Last Used</span>
          <p className="text-slate-100 mt-1">{formatDate(client.last_used_at)}</p>
        </div>
      </div>

      {client.suspension_reason && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <span className="text-slate-400 text-sm">Suspension Reason</span>
          <p className="text-amber-300 mt-1">{client.suspension_reason}</p>
          {client.suspended_at && (
            <p className="text-slate-500 text-xs mt-1">
              {client.status === "blocked" ? "Blocked" : "Suspended"} at {formatDate(client.suspended_at)}
              {client.suspended_by && ` by ${client.suspended_by}`}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
