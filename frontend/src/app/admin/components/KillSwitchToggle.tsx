import { useState } from "react";
import { Users, Target, Power, PowerOff } from "lucide-react";
import { cn } from "@/lib/utils";
import { useHoldToConfirm } from "../hooks";

export function KillSwitchToggle({
  name,
  enabled,
  disabledAt,
  disabledBy,
  reason,
  onToggle,
  type,
}: {
  name: string;
  enabled: boolean;
  disabledAt: string | null;
  disabledBy: string | null;
  reason: string | null;
  onToggle: (reason: string) => void;
  type: "client";
}) {
  const [auditNote, setAuditNote] = useState("");
  const [showInput, setShowInput] = useState(false);

  const { isHolding, progress, start, cancel } = useHoldToConfirm(() => {
    if (!enabled || auditNote.trim()) {
      onToggle(auditNote);
      setAuditNote("");
      setShowInput(false);
    }
  });

  const handleClick = () => {
    if (enabled) {
      setShowInput(true);
    } else {
      start();
    }
  };

  return (
    <div
      className={cn(
        "group relative p-4 rounded-xl border transition-all duration-200",
        enabled
          ? "bg-slate-900/30 border-slate-800 hover:border-slate-700"
          : "bg-red-950/30 border-red-900/50 hover:border-red-800"
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div
            className={cn(
              "p-2 rounded-lg",
              enabled ? "bg-emerald-900/30 text-emerald-400" : "bg-red-900/30 text-red-400"
            )}
          >
            {type === "client" ? <Users className="w-4 h-4" /> : <Target className="w-4 h-4" />}
          </div>
          <div>
            <h3 className="font-medium text-slate-100">{name}</h3>
            {!enabled && disabledAt && (
              <p className="text-xs text-slate-500">
                Disabled {new Date(disabledAt).toLocaleDateString()}
                {disabledBy && ` by ${disabledBy}`}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3">
          {!enabled && reason && (
            <span className="text-xs text-red-400 max-w-[200px] truncate">{reason}</span>
          )}

          <button
            onClick={handleClick}
            onMouseDown={!enabled ? start : undefined}
            onMouseUp={!enabled ? cancel : undefined}
            onMouseLeave={!enabled ? cancel : undefined}
            className={cn(
              "relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all",
              enabled
                ? "bg-red-600/20 text-red-400 hover:bg-red-600/30"
                : "bg-emerald-600/20 text-emerald-400 hover:bg-emerald-600/30"
            )}
          >
            {isHolding && (
              <div className="absolute inset-0 bg-current opacity-20" style={{ width: `${progress}%` }} />
            )}
            <span className="relative flex items-center gap-2">
              {enabled ? (
                <>
                  <PowerOff className="w-4 h-4" />
                  Disable
                </>
              ) : (
                <>
                  <Power className="w-4 h-4" />
                  Hold to Enable
                </>
              )}
            </span>
          </button>
        </div>
      </div>

      {showInput && enabled && (
        <div className="mt-4 pt-4 border-t border-slate-800">
          <label className="block text-sm text-slate-400 mb-2">Audit note (required)</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={auditNote}
              onChange={(e) => setAuditNote(e.target.value)}
              placeholder="Reason for disabling..."
              className="flex-1 px-3 py-2 rounded-lg bg-slate-800/50 border border-slate-700 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
            />
            <button
              disabled={!auditNote.trim()}
              onMouseDown={auditNote.trim() ? start : undefined}
              onMouseUp={cancel}
              onMouseLeave={cancel}
              className={cn(
                "relative overflow-hidden px-4 py-2 rounded-lg font-medium text-sm transition-all",
                auditNote.trim()
                  ? "bg-red-600 text-white hover:bg-red-500"
                  : "bg-slate-700 text-slate-500 cursor-not-allowed"
              )}
            >
              {isHolding && (
                <div className="absolute inset-0 bg-white opacity-20" style={{ width: `${progress}%` }} />
              )}
              <span className="relative">Hold to Confirm</span>
            </button>
            <button
              onClick={() => {
                setShowInput(false);
                setAuditNote("");
              }}
              className="px-3 py-2 rounded-lg bg-slate-800 text-slate-400 hover:bg-slate-700"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
