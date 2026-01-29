import { Filter, Bot } from "lucide-react";

interface FiltersProps {
  clientFilter: string;
  setClientFilter: (value: string) => void;
  agentFilter: string;
  setAgentFilter: (value: string) => void;
  toolTypeFilter: string | undefined;
  setToolTypeFilter: (value: string | undefined) => void;
  statusFilter: number | undefined;
  setStatusFilter: (value: number | undefined) => void;
  rejectedOnly: boolean;
  setRejectedOnly: (value: boolean) => void;
}

export function Filters({
  clientFilter,
  setClientFilter,
  agentFilter,
  setAgentFilter,
  toolTypeFilter,
  setToolTypeFilter,
  statusFilter,
  setStatusFilter,
  rejectedOnly,
  setRejectedOnly,
}: FiltersProps) {
  return (
    <div className="flex flex-wrap gap-3">
      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700">
        <Filter className="h-4 w-4 text-slate-400" />
        <input
          type="text"
          placeholder="Filter by client ID..."
          value={clientFilter}
          onChange={(e) => { setClientFilter(e.target.value); }}
          className="bg-transparent border-none outline-none text-sm text-slate-100 placeholder-slate-500 w-36"
        />
      </div>

      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700">
        <Bot className="h-4 w-4 text-slate-400" />
        <input
          type="text"
          placeholder="Filter by agent..."
          value={agentFilter}
          onChange={(e) => { setAgentFilter(e.target.value); }}
          className="bg-transparent border-none outline-none text-sm text-slate-100 placeholder-slate-500 w-32"
        />
      </div>

      <select
        value={toolTypeFilter || ""}
        onChange={(e) => { setToolTypeFilter(e.target.value || undefined); }}
        className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-100"
      >
        <option value="">All Tool Types</option>
        <option value="api">API</option>
        <option value="cli">CLI</option>
        <option value="sdk">SDK</option>
      </select>

      <select
        value={statusFilter || ""}
        onChange={(e) => { setStatusFilter(e.target.value ? parseInt(e.target.value) : undefined); }}
        className="px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-sm text-slate-100"
      >
        <option value="">All Status Codes</option>
        <option value="200">200 OK</option>
        <option value="400">400 Bad Request</option>
        <option value="403">403 Forbidden</option>
        <option value="500">500 Error</option>
      </select>

      <label className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 cursor-pointer">
        <input
          type="checkbox"
          checked={rejectedOnly}
          onChange={(e) => { setRejectedOnly(e.target.checked); }}
          className="rounded bg-slate-700 border-slate-600 text-amber-500 focus:ring-amber-500/50"
        />
        <span className="text-sm text-slate-300">Rejected only</span>
      </label>
    </div>
  );
}
