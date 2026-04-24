"use client";

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { PROVIDER_COLORS } from "@/components/settings/constants";
import type { ModelOption } from "@/components/chat/use-models";

interface ModelRadarProps {
  models: ModelOption[];
  size?: "sm" | "md" | "lg";
}

const CHART_COLORS: Record<string, string> = {
  claude: "#f59e0b",     // amber-500
  gemini: "#3b82f6",     // blue-500
  openai: "#10b981",     // green-500
  openrouter: "#a855f7", // purple-500
  xai: "#ef4444",        // red-500
  zhipu: "#14b8a6",      // teal-500
  minimax: "#f97316",    // orange-500
  nvidia: "#84cc16",     // lime-500
};

export function ModelRadar({ models, size = "md" }: ModelRadarProps) {
  if (models.length === 0) return null;

  const chartData = [
    { category: "Coding", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.coding }), {}) },
    { category: "Reasoning", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.reasoning }), {}) },
    { category: "Planning", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.planning }), {}) },
    { category: "Tool Use", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.tool_use }), {}) },
    { category: "Instruction", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.instruction }), {}) },
    { category: "Design", ...models.reduce((acc, m, i) => ({ ...acc, [`model${i}`]: m.scores.design }), {}) },
  ];

  const heightMap = {
    sm: 180,
    md: 280,
    lg: 400,
  };

  return (
    <ResponsiveContainer width="100%" height={heightMap[size]}>
      <RadarChart data={chartData}>
        <PolarGrid stroke="#334155" strokeDasharray="3 3" />
        <PolarAngleAxis
          dataKey="category"
          tick={{ fill: "#94a3b8", fontSize: size === "sm" ? 10 : 12 }}
        />
        <PolarRadiusAxis
          angle={90}
          domain={[0, 100]}
          tick={{ fill: "#64748b", fontSize: 10 }}
        />
        {models.map((model, index) => (
          <Radar
            key={model.id}
            name={model.name}
            dataKey={`model${index}`}
            stroke={CHART_COLORS[model.provider]}
            fill={CHART_COLORS[model.provider]}
            fillOpacity={models.length === 1 ? 0.3 : 0.15}
            strokeWidth={2}
          />
        ))}
        {models.length > 1 && (
          <Legend
            wrapperStyle={{
              fontSize: "12px",
              paddingTop: "10px",
            }}
          />
        )}
      </RadarChart>
    </ResponsiveContainer>
  );
}
