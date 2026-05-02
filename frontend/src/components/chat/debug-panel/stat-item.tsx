export function StatItem({
  label,
  value,
  unit,
}: {
  label: string
  value: string | number
  unit?: string
}) {
  return (
    <div className="flex justify-between items-center py-1">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-xs font-mono font-semibold text-foreground">
        {value}
        {unit && <span className="text-muted-foreground ml-0.5">{unit}</span>}
      </span>
    </div>
  )
}
