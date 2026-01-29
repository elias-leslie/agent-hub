import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import type { ModelOption } from "./model-options";

interface MentionPopupProps {
  options: ModelOption[];
  selectedIndex: number;
  onSelect: (model: ModelOption) => void;
  filter: string;
}

export function MentionPopup({
  options,
  selectedIndex,
  onSelect,
  filter,
}: MentionPopupProps) {
  const popupRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (popupRef.current && selectedIndex >= 0) {
      const selectedItem = popupRef.current.children[selectedIndex] as HTMLElement;
      selectedItem?.scrollIntoView({ block: "nearest" });
    }
  }, [selectedIndex]);

  return (
    <div
      ref={popupRef}
      className={cn(
        "absolute bottom-full left-0 mb-2 z-50",
        "bg-white/95 dark:bg-gray-900/95 backdrop-blur-xl",
        "border border-gray-200/80 dark:border-gray-700/80",
        "rounded-xl shadow-xl shadow-black/10 dark:shadow-black/30",
        "py-2 min-w-[220px] max-h-[280px] overflow-y-auto",
        "animate-in fade-in slide-in-from-bottom-2 duration-200"
      )}
      role="listbox"
      aria-label="Select a model"
    >
      <div className="px-3 pb-2 mb-1 border-b border-gray-100 dark:border-gray-800">
        <span className="text-xs font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wider">
          {filter ? `Matching "${filter}"` : "Select Model"}
        </span>
      </div>
      {options.map((option, index) => {
        const isSelected = index === selectedIndex;
        const isClaudeProvider = option.provider === "claude";

        return (
          <button
            key={option.alias}
            type="button"
            role="option"
            aria-selected={isSelected}
            onClick={() => onSelect(option)}
            className={cn(
              "w-full px-3 py-2.5 text-left flex items-center gap-3",
              "transition-all duration-150 ease-out",
              "focus:outline-none",
              isSelected
                ? isClaudeProvider
                  ? "bg-amber-50 dark:bg-amber-900/20"
                  : "bg-blue-50 dark:bg-blue-900/20"
                : "hover:bg-gray-50 dark:hover:bg-gray-800/50"
            )}
          >
            <span
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg text-sm font-bold",
                "transition-transform duration-150",
                isSelected && "scale-105",
                isClaudeProvider
                  ? "bg-gradient-to-br from-amber-400 to-orange-500 text-white"
                  : "bg-gradient-to-br from-blue-400 to-cyan-500 text-white"
              )}
            >
              {option.alias.charAt(0).toUpperCase()}
            </span>
            <div className="flex-1 min-w-0">
              <div
                className={cn(
                  "font-medium text-sm",
                  isClaudeProvider
                    ? "text-amber-700 dark:text-amber-300"
                    : "text-blue-700 dark:text-blue-300"
                )}
              >
                @{option.alias}
              </div>
              <div className="text-xs text-gray-500 dark:text-gray-400">
                {option.hint}
              </div>
            </div>
            {isSelected && (
              <span className="text-xs text-gray-400 dark:text-gray-500 font-mono">
                ↵
              </span>
            )}
          </button>
        );
      })}
      {options.length === 0 && (
        <div className="px-3 py-4 text-center text-sm text-gray-400 dark:text-gray-500">
          No matching models
        </div>
      )}
    </div>
  );
}
