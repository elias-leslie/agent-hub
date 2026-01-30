import { cn } from "@/lib/utils";
import { CopyButton } from "./CopyButton";
import type { BlockedRequest } from "../api";

export function ExpandedRowContent({ request }: { request: BlockedRequest }) {
  return (
    <div className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
      {/* Main Details */}
      <div className="md:col-span-2 space-y-3">
        <div>
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
            Block Reason
          </h4>
          <p className="text-sm text-red-400 font-mono bg-red-950/30 px-3 py-2 rounded-lg border border-red-900/50">
            {request.block_reason}
          </p>
        </div>

        <div>
          <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
            Endpoint
          </h4>
          <div className="flex items-center gap-2">
            <code className="text-sm text-slate-300 font-mono bg-slate-800/50 px-3 py-2 rounded-lg flex-1">
              {request.endpoint}
            </code>
            <CopyButton text={request.endpoint} />
          </div>
        </div>

        {request.source_path && (
          <div>
            <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 mb-1">
              Source Path
            </h4>
            <div className="flex items-center gap-2">
              <code className="text-sm text-slate-400 font-mono bg-slate-800/50 px-3 py-2 rounded-lg flex-1 truncate">
                {request.source_path}
              </code>
              <CopyButton text={request.source_path} />
            </div>
          </div>
        )}
      </div>

      {/* Metadata */}
      <div className="space-y-3">
        <h4 className="text-[9px] font-bold uppercase tracking-widest text-slate-500 border-b border-slate-800 pb-2">
          Request Info
        </h4>
        <div className="space-y-2 text-sm">
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Client</span>
            <span className={cn(
              "font-mono",
              request.client_name === "<unknown>" ? "text-red-400 font-bold" : "text-amber-400"
            )}>
              {request.client_name === "<unknown>" ? "UNKNOWN" : request.client_name || "—"}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-slate-500">Time</span>
            <span className="font-mono text-slate-400 tabular-nums">
              {new Date(request.timestamp).toLocaleString()}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
