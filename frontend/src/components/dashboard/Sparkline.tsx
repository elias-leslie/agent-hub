/**
 * Sparkline chart component for displaying trend data.
 * Supports two rendering modes:
 * - Fixed-size: pass width/height for pixel-based rendering (table cells)
 * - Responsive: omit width/height for viewBox-based rendering (fills container)
 */
export function Sparkline({
  data,
  color = 'emerald',
  width,
  height,
  showDot = false,
}: {
  data: number[]
  color?: 'emerald' | 'blue' | 'amber' | 'red'
  width?: number
  height?: number
  showDot?: boolean
}) {
  let chartData = data
  if (!chartData || chartData.length === 0) {
    chartData = [0, 0, 0, 0, 0, 0, 0]
  } else if (chartData.length === 1) {
    chartData = [0, 0, 0, 0, 0, 0, chartData[0]]
  }

  const min = Math.min(...chartData)
  const max = Math.max(...chartData)
  const range = max - min || 1

  const colorMap = {
    emerald: { stroke: '#10b981', fill: '#10b98120' },
    blue: { stroke: '#3b82f6', fill: '#3b82f620' },
    amber: { stroke: '#f59e0b', fill: '#f59e0b20' },
    red: { stroke: '#ef4444', fill: '#ef444420' },
  }

  const colors = colorMap[color]

  // Responsive mode: viewBox-based, fills container
  if (!width || !height) {
    const vw = 100
    const vh = 100
    const points = chartData
      .map((v, i) => {
        const x = (i / (chartData.length - 1)) * vw
        const y = vh - ((v - min) / range) * (vh * 0.8) - vh * 0.1
        return `${x},${y}`
      })
      .join(' ')

    return (
      <svg
        viewBox={`0 0 ${vw} ${vh}`}
        preserveAspectRatio="none"
        className="w-full h-full"
      >
        <polygon points={`0,${vh} ${points} ${vw},${vh}`} fill={colors.fill} />
        <polyline
          points={points}
          fill="none"
          stroke={colors.stroke}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {showDot && (
          <circle
            cx={vw}
            cy={
              vh -
              ((chartData[chartData.length - 1] - min) / range) * (vh * 0.8) -
              vh * 0.1
            }
            r="3"
            fill={colors.stroke}
          />
        )}
      </svg>
    )
  }

  // Fixed-size mode: pixel-based rendering
  const padding = 2
  const effectiveWidth = width - padding * 2
  const effectiveHeight = height - padding * 2

  const points = chartData.map((value, index) => {
    const x = padding + (index / (chartData.length - 1)) * effectiveWidth
    const y =
      padding + effectiveHeight - ((value - min) / range) * effectiveHeight
    return `${x},${y}`
  })

  const fillPoints = [
    `${padding},${height - padding}`,
    ...points,
    `${width - padding},${height - padding}`,
  ].join(' ')

  return (
    <svg width={width} height={height} className="flex-shrink-0">
      <polygon points={fillPoints} fill={colors.fill} />
      <polyline
        points={points.join(' ')}
        fill="none"
        stroke={colors.stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
