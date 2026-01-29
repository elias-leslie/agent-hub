/**
 * Sparkline chart component for displaying trend data.
 * Uses SVG for crisp rendering at small sizes.
 */
export function Sparkline({
  data,
  color = "emerald",
  width = 60,
  height = 20,
}: {
  data: number[];
  color?: "emerald" | "blue" | "amber" | "red";
  width?: number;
  height?: number;
}) {
  if (!data || data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[9px] text-slate-400"
        style={{ width, height }}
      >
        No data
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const padding = 2;
  const effectiveWidth = width - padding * 2;
  const effectiveHeight = height - padding * 2;

  const points = data.map((value, index) => {
    const x = padding + (index / (data.length - 1)) * effectiveWidth;
    const y = padding + effectiveHeight - ((value - min) / range) * effectiveHeight;
    return `${x},${y}`;
  });

  const colorMap = {
    emerald: { stroke: "#10b981", fill: "#10b98120" },
    blue: { stroke: "#3b82f6", fill: "#3b82f620" },
    amber: { stroke: "#f59e0b", fill: "#f59e0b20" },
    red: { stroke: "#ef4444", fill: "#ef444420" },
  };

  const colors = colorMap[color];

  // Create fill polygon (line + bottom edge)
  const fillPoints = [
    `${padding},${height - padding}`,
    ...points,
    `${width - padding},${height - padding}`,
  ].join(" ");

  return (
    <svg width={width} height={height} className="flex-shrink-0">
      <polygon points={fillPoints} fill={colors.fill} />
      <polyline
        points={points.join(" ")}
        fill="none"
        stroke={colors.stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
