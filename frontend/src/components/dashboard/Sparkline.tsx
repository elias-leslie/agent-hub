// ─────────────────────────────────────────────────────────────────────────────
// SPARKLINE CHART - Compact time series
// ─────────────────────────────────────────────────────────────────────────────

export function Sparkline({ data, color = "emerald" }: { data: number[]; color?: "emerald" | "amber" | "blue" }) {
  if (data.length === 0) return <div className="h-full w-full bg-slate-800 rounded animate-pulse" />;

  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;

  const points = data
    .map((v, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - ((v - min) / range) * 80 - 10;
      return `${x},${y}`;
    })
    .join(" ");

  const colorMap = {
    emerald: { stroke: "stroke-emerald-500", fill: "fill-emerald-500/10", dot: "fill-emerald-500" },
    amber: { stroke: "stroke-amber-500", fill: "fill-amber-500/10", dot: "fill-amber-500" },
    blue: { stroke: "stroke-blue-500", fill: "fill-blue-500/10", dot: "fill-blue-500" },
  };

  const colors = colorMap[color];

  return (
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
      {/* Area fill */}
      <polygon points={`0,100 ${points} 100,100`} className={colors.fill} />
      {/* Line */}
      <polyline
        points={points}
        fill="none"
        className={colors.stroke}
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      {/* End dot */}
      {data.length > 0 && (
        <circle
          cx={100}
          cy={100 - ((data[data.length - 1] - min) / range) * 80 - 10}
          r="3"
          className={colors.dot}
        />
      )}
    </svg>
  );
}
