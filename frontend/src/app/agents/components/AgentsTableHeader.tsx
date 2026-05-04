import { Activity, Clock, DollarSign } from 'lucide-react'
import { SortableHeader } from '@/components/ui/SortableHeader'
import type { SortDirection, SortField } from '../lib/types'

export function AgentsTableHeader({
  sortField,
  sortDirection,
  onSort,
}: {
  sortField: SortField
  sortDirection: SortDirection
  onSort: (field: SortField) => void
}) {
  return (
    <div className="min-w-[940px] border-b border-slate-700/80 bg-slate-900/95">
      <div className="grid grid-cols-[220px_1fr_130px_130px_110px_40px] items-center gap-3 px-5 py-3">
        <SortableHeader
          label="Agent"
          field="name"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
        />
        <SortableHeader
          label="Model"
          field="model"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
        />
        <SortableHeader
          label="Requests 24h"
          field="requests"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<Activity className="h-3 w-3" />}
        />
        <SortableHeader
          label="Latency"
          field="latency"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<Clock className="h-3 w-3" />}
        />
        <SortableHeader
          label="Cost 24h"
          field="cost"
          currentField={sortField}
          direction={sortDirection}
          onSort={onSort}
          icon={<DollarSign className="h-3 w-3" />}
        />
        <div />
      </div>
    </div>
  )
}
