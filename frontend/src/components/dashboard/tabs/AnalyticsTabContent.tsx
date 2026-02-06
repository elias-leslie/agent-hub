import { Layers, BarChart3 } from "lucide-react";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { formatCurrency } from "@/lib/formatters";
import type { CostAggregationResponse } from "@/lib/api";

// ─────────────────────────────────────────────────────────────────────────────
// ANALYTICS TAB CONTENT
// ─────────────────────────────────────────────────────────────────────────────

const PIE_COLORS = ["#f59e0b", "#3b82f6", "#10b981", "#8b5cf6", "#ec4899"];

export function AnalyticsTabContent({
  costsByProject,
  costsByModel,
  isLoading,
}: {
  costsByProject: CostAggregationResponse | undefined;
  costsByModel: CostAggregationResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-2 gap-4 h-48">
        <div className="bg-slate-800 rounded animate-pulse" />
        <div className="bg-slate-800 rounded animate-pulse" />
      </div>
    );
  }

  const pieData = costsByProject?.aggregations.slice(0, 5).map((agg) => ({
    name: agg.group_key,
    value: agg.total_cost_usd,
  })) || [];

  const barData = costsByModel?.aggregations.slice(0, 5).map((agg) => ({
    model: agg.group_key.replace("claude-", "").replace("gemini-", "g-").slice(0, 10),
    input: agg.input_tokens / 1000,
    output: agg.output_tokens / 1000,
  })) || [];

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {/* Cost by Project Pie */}
      <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
          <Layers className="h-3 w-3 text-amber-500" />
          Cost by Project
        </h4>
        {pieData.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                innerRadius={35}
                outerRadius={55}
                paddingAngle={2}
                dataKey="value"
              >
                {pieData.map((_, idx) => (
                  <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value) => formatCurrency(Number(value))}
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #1e293b",
                  borderRadius: "8px",
                  fontSize: "12px",
                  color: "#f1f5f9",
                  boxShadow: "0 10px 15px -3px rgb(0 0 0 / 0.1)",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-slate-500 text-xs font-mono">
            NO COST DATA
          </div>
        )}
      </div>

      {/* Token Usage by Model Bar */}
      <div className="p-4 rounded-lg bg-slate-800/40 border border-slate-700/50">
        <h4 className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 mb-3 flex items-center gap-1.5">
          <BarChart3 className="h-3 w-3 text-blue-500" />
          Tokens by Model (K)
        </h4>
        {barData.length > 0 ? (
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={barData} layout="vertical" barGap={0} barCategoryGap="20%">
              <XAxis type="number" tick={{ fontSize: 10, fill: "#64748b" }} tickFormatter={(v) => `${v}K`} hide />
              <YAxis type="category" dataKey="model" tick={{ fontSize: 9, fill: "#94a3b8" }} width={60} />
              <Tooltip
                formatter={(value) => `${Number(value).toFixed(1)}K`}
                contentStyle={{
                  background: "#0f172a",
                  border: "1px solid #1e293b",
                  borderRadius: "8px",
                  fontSize: "12px",
                  color: "#f1f5f9",
                  boxShadow: "0 10px 15px -3px rgb(0 0 0 / 0.1)",
                }}
              />
              <Bar dataKey="input" stackId="a" fill="#10b981" radius={[0, 0, 0, 0]} />
              <Bar dataKey="output" stackId="a" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-40 flex items-center justify-center text-slate-500 text-xs font-mono">
            NO TOKEN DATA
          </div>
        )}
      </div>
    </div>
  );
}
