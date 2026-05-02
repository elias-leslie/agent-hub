import { useEffect, useRef } from "react";
import { cn } from "../lib/utils";
import type { ModelOption } from "./use-models";

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
        "bg-popover text-popover-foreground backdrop-blur-xl",
        "border border-border",
        "rounded-xl shadow-xl shadow-black/20",
        "py-2 min-w-[220px] max-h-[280px] overflow-y-auto",
        "animate-in fade-in slide-in-from-bottom-2 duration-200"
      )}
      role="listbox"
      aria-label="Select a model"
    >
      <div className="px-3 pb-2 mb-1 border-b border-border">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          {filter ? `Matching "${filter}"` : "Select Model"}
        </span>
      </div>
      {options.map((option, index) => {
        const isSelected = index === selectedIndex;
        const providerColors = {
          claude: {
            bg: "bg-amber-900/20",
            icon: "bg-gradient-to-br from-amber-400 to-orange-500 text-white",
            text: "text-amber-300",
          },
          gemini: {
            bg: "bg-blue-900/20",
            icon: "bg-gradient-to-br from-blue-400 to-cyan-500 text-white",
            text: "text-blue-300",
          },
          openai: {
            bg: "bg-green-900/20",
            icon: "bg-gradient-to-br from-green-400 to-emerald-500 text-white",
            text: "text-green-300",
          },
          xai: {
            bg: "bg-red-900/20",
            icon: "bg-gradient-to-br from-red-400 to-rose-500 text-white",
            text: "text-red-300",
          },
          zhipu: {
            bg: "bg-teal-900/20",
            icon: "bg-gradient-to-br from-teal-400 to-cyan-500 text-white",
            text: "text-teal-300",
          },
          openrouter: {
            bg: "bg-purple-900/20",
            icon: "bg-gradient-to-br from-purple-400 to-violet-500 text-white",
            text: "text-purple-300",
          },
        } as const;

        const colors = providerColors[option.provider as keyof typeof providerColors] ?? providerColors.gemini;

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
                ? colors.bg
                : "hover:bg-accent"
            )}
          >
            <span
              className={cn(
                "flex items-center justify-center w-8 h-8 rounded-lg text-sm font-bold",
                "transition-transform duration-150",
                isSelected && "scale-105",
                colors.icon
              )}
            >
              {option.alias.charAt(0).toUpperCase()}
            </span>
            <div className="flex-1 min-w-0">
              <div
                className={cn(
                  "font-medium text-sm",
                  colors.text
                )}
              >
                @{option.alias}
              </div>
              <div className="text-xs text-muted-foreground">
                {option.hint}
              </div>
            </div>
            {isSelected && (
              <span className="text-xs text-muted-foreground font-mono">
                ↵
              </span>
            )}
          </button>
        );
      })}
      {options.length === 0 && (
        <div className="px-3 py-4 text-center text-sm text-muted-foreground">
          No matching models
        </div>
      )}
    </div>
  );
}
