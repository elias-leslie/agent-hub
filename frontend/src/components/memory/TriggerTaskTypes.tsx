"use client";

import { useState } from "react";
import { Tag, X, Plus, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { updateEpisodeProperties } from "@/lib/memory-api";

interface TriggerTaskTypesProps {
  episodeUuid: string;
  initialTriggerTypes: string[];
}

const COMMON_TASK_TYPES = ["database", "frontend", "backend", "testing", "deployment", "migration", "refactor", "security"];

export function TriggerTaskTypes({ episodeUuid, initialTriggerTypes }: TriggerTaskTypesProps) {
  const [triggerTypes, setTriggerTypes] = useState<string[]>(initialTriggerTypes);
  const [newTriggerType, setNewTriggerType] = useState("");
  const [isUpdatingTriggers, setIsUpdatingTriggers] = useState(false);
  const [triggersError, setTriggersError] = useState<string | null>(null);

  const suggestedTypes = COMMON_TASK_TYPES.filter(t => !triggerTypes.includes(t));

  const handleAddTriggerType = async () => {
    const trimmed = newTriggerType.trim().toLowerCase();
    if (!trimmed || triggerTypes.includes(trimmed)) {
      setNewTriggerType("");
      return;
    }

    const updatedTypes = [...triggerTypes, trimmed];
    setIsUpdatingTriggers(true);
    setTriggersError(null);
    try {
      await updateEpisodeProperties(episodeUuid, { trigger_task_types: updatedTypes });
      setTriggerTypes(updatedTypes);
      setNewTriggerType("");
    } catch (err) {
      setTriggersError(err instanceof Error ? err.message : "Failed to update triggers");
    } finally {
      setIsUpdatingTriggers(false);
    }
  };

  const handleRemoveTriggerType = async (typeToRemove: string) => {
    const updatedTypes = triggerTypes.filter(t => t !== typeToRemove);
    setIsUpdatingTriggers(true);
    setTriggersError(null);
    try {
      await updateEpisodeProperties(episodeUuid, { trigger_task_types: updatedTypes });
      setTriggerTypes(updatedTypes);
    } catch (err) {
      setTriggersError(err instanceof Error ? err.message : "Failed to update triggers");
    } finally {
      setIsUpdatingTriggers(false);
    }
  };

  return (
    <div>
      <h4 className="text-[10px] font-bold uppercase tracking-widest text-slate-400 mb-2 flex items-center gap-1.5">
        <Tag className="h-3 w-3" />
        Trigger Task Types
        {triggerTypes.length > 0 && (
          <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300">
            {triggerTypes.length}
          </span>
        )}
      </h4>
      <p className="text-[10px] text-slate-400 mb-2">
        Auto-inject this reference when task_type matches
      </p>

      {/* Existing trigger types */}
      <div className="flex flex-wrap gap-1.5 mb-2">
        {triggerTypes.map((type) => (
          <span
            key={type}
            className="flex items-center gap-1 px-2 py-1 text-[10px] rounded-full bg-cyan-50 dark:bg-cyan-950/30 text-cyan-700 dark:text-cyan-300 border border-cyan-200 dark:border-cyan-800"
          >
            {type}
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleRemoveTriggerType(type);
              }}
              disabled={isUpdatingTriggers}
              className="hover:text-cyan-900 dark:hover:text-cyan-100 disabled:opacity-50"
            >
              <X className="h-2.5 w-2.5" />
            </button>
          </span>
        ))}
        {triggerTypes.length === 0 && (
          <span className="text-[10px] text-slate-400 italic">No triggers set</span>
        )}
      </div>

      {/* Add new trigger type */}
      <div className="flex gap-1.5">
        <input
          type="text"
          value={newTriggerType}
          onChange={(e) => setNewTriggerType(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleAddTriggerType();
            }
          }}
          onClick={(e) => e.stopPropagation()}
          placeholder="e.g., database, migration"
          disabled={isUpdatingTriggers}
          className={cn(
            "flex-1 px-2 py-1 text-[10px] rounded-md",
            "bg-slate-800/50 border border-slate-700",
            "text-slate-300 placeholder:text-slate-400",
            "focus:outline-none focus:ring-1 focus:ring-cyan-500/50",
            "disabled:opacity-50"
          )}
        />
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleAddTriggerType();
          }}
          disabled={isUpdatingTriggers || !newTriggerType.trim()}
          className={cn(
            "px-2 py-1 rounded-md text-[10px] font-medium transition-colors",
            "bg-cyan-50 dark:bg-cyan-900/20 text-cyan-600 dark:text-cyan-400",
            "hover:bg-cyan-100 dark:hover:bg-cyan-900/30",
            "border border-cyan-200 dark:border-cyan-800",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {isUpdatingTriggers ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <Plus className="h-3 w-3" />
          )}
        </button>
      </div>

      {/* Suggested types */}
      {suggestedTypes.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {suggestedTypes.slice(0, 5).map((type) => (
            <button
              key={type}
              onClick={(e) => {
                e.stopPropagation();
                setNewTriggerType(type);
              }}
              className="px-1.5 py-0.5 text-[9px] rounded bg-slate-800 text-slate-400 hover:bg-cyan-50 dark:hover:bg-cyan-900/20 hover:text-cyan-600 dark:hover:text-cyan-400 transition-colors"
            >
              +{type}
            </button>
          ))}
        </div>
      )}

      {triggersError && (
        <p className="text-[10px] text-red-400 mt-1">{triggersError}</p>
      )}
    </div>
  );
}
