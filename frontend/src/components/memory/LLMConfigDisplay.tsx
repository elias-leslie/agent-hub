import { Cpu } from 'lucide-react'
import type { LLMConfig } from '@/lib/api/memory-settings'

export function LLMConfigDisplay({ config }: { config: LLMConfig }) {
  return (
    <div className="space-y-2 p-3 rounded-lg bg-slate-800/50">
      <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
        <Cpu className="w-4 h-4" />
        LLM Configuration
      </div>
      <div className="space-y-1.5 text-sm">
        <div className="flex justify-between items-center">
          <span className="text-slate-500">Reranker</span>
          <code className="text-xs font-mono text-slate-300 bg-slate-700 px-1.5 py-0.5 rounded">
            {config.reranker_model}
          </code>
        </div>
        <div className="flex justify-between items-center">
          <span className="text-slate-500">Embeddings</span>
          <code className="text-xs font-mono text-slate-300 bg-slate-700 px-1.5 py-0.5 rounded">
            {config.embedding_model}
          </code>
        </div>
      </div>
    </div>
  )
}
