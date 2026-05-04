import { Tags } from 'lucide-react'
import { parseTagsFromInput } from './utils'

interface TagFilteringSectionProps {
  audienceTags: string[]
  excludeTags: string[]
  excludeMemoryUuids: string[]
  onUpdateTags: (
    field: 'audience_tags' | 'exclude_tags' | 'exclude_memory_uuids',
    tags: string[],
  ) => void
}

export function TagFilteringSection({
  audienceTags,
  excludeTags,
  excludeMemoryUuids,
  onUpdateTags,
}: TagFilteringSectionProps) {
  const handleTagChange = (
    field: 'audience_tags' | 'exclude_tags' | 'exclude_memory_uuids',
    value: string,
  ) => {
    const tags = parseTagsFromInput(value)
    onUpdateTags(field, tags)
  }

  return (
    <div className="space-y-5 p-5 rounded-lg border border-slate-700 bg-slate-800/50">
      <div className="flex items-center gap-2">
        <Tags className="h-5 w-5 text-slate-400" />
        <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">
          Tag Filtering
        </h3>
      </div>

      <p className="text-xs text-slate-400">
        Audience tags route reference memories to this agent. Exclude tags and
        explicit UUID suppressions are precision escape hatches when global
        rules or broad tags are too blunt.
      </p>

      {/* Audience Tags */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-400">
          Audience Tags
        </label>
        <input
          type="text"
          value={audienceTags.join(', ')}
          onChange={(e) => handleTagChange('audience_tags', e.target.value)}
          placeholder="e.g. agent:debugger, workflow:heartbeat, provider:codex"
          className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
        />
        <p className="text-[11px] text-slate-500">
          Only tagged reference memories with at least one matching tag remain
          eligible.
        </p>
      </div>

      {/* Exclude Tags */}
      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-400">
          Exclude Tags
        </label>
        <input
          type="text"
          value={excludeTags.join(', ')}
          onChange={(e) => handleTagChange('exclude_tags', e.target.value)}
          placeholder="e.g. deprecated, internal, draft"
          className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
        />
        <p className="text-[11px] text-slate-500">
          Force-hide memories with these tags, even if they would otherwise
          match.
        </p>
      </div>

      <div className="space-y-1.5">
        <label className="text-xs font-medium text-slate-400">
          Exclude Memory UUIDs
        </label>
        <input
          type="text"
          value={excludeMemoryUuids.join(', ')}
          onChange={(e) =>
            handleTagChange('exclude_memory_uuids', e.target.value)
          }
          placeholder="e.g. 1234abcd, 5678efgh"
          className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
        />
        <p className="text-[11px] text-slate-500">
          Force-hide specific memories for this agent by UUID prefix or full
          UUID.
        </p>
      </div>
    </div>
  )
}
