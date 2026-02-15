import { cn } from "@/lib/utils";
import type { ModelOption } from "@agent-hub/chat-ui";
import type { ComplexityTier } from "./tier-matrix-grid";
import { PROVIDER_COLORS } from "./constants";
import { MatrixCell } from "./tier-matrix-cell";

const TIER_LABELS: Record<ComplexityTier, string> = {
  1: "Simple",
  2: "Medium",
  3: "Complex",
  4: "Expert",
};

interface MatrixTableProps {
  providers: string[];
  tiers: ComplexityTier[];
  matrixData: Record<string, Record<ComplexityTier, ModelOption | null>>;
  hoveredCell: string | null;
  onCellHover: (cellKey: string | null) => void;
}

export function MatrixTable({ providers, tiers, matrixData, hoveredCell, onCellHover }: MatrixTableProps) {
  return (
    <div className="overflow-x-auto">
      <div className="inline-block min-w-full align-middle">
        <table className="w-full border-collapse">
          <thead>
            <tr>
              <th className="p-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                Complexity
              </th>
              {providers.map((provider) => (
                <th
                  key={provider}
                  className="p-3 text-center text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700"
                >
                  <div className="flex items-center justify-center gap-1.5">
                    <div className={cn("w-2 h-2 rounded-full", PROVIDER_COLORS[provider]?.dot || "bg-slate-400")} />
                    <span className="capitalize">{provider}</span>
                  </div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tiers.map((tier) => (
              <tr key={tier}>
                <td className="p-3 text-sm font-medium text-slate-700 dark:text-slate-300 border-b border-slate-200 dark:border-slate-700">
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium font-mono tabular-nums border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                      T{tier}
                    </span>
                    <span>{TIER_LABELS[tier]}</span>
                  </div>
                </td>
                {providers.map((provider) => {
                  const model = matrixData[provider]?.[tier];
                  const cellKey = `${provider}-${tier}`;
                  const isHovered = hoveredCell === cellKey;
                  return (
                    <MatrixCell
                      key={provider}
                      model={model}
                      provider={provider}
                      isHovered={isHovered}
                      onMouseEnter={() => onCellHover(cellKey)}
                      onMouseLeave={() => onCellHover(null)}
                    />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
