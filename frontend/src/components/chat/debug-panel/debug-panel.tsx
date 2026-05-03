import type { ChatMessage } from '@agent-hub/chat-ui'
import { Cpu, FileText, Hash, Tag, Zap } from 'lucide-react'
import { useState } from 'react'
import type { Agent, AgentPreview } from '@/types/agent'
import { DebugSection } from './debug-section'
import { StatItem } from './stat-item'

export interface DebugTrace {
  model_used: string
  input_tokens: number
  output_tokens: number
  latency_ms: number
  mandates_injected: number
  mandate_uuids: string[]
  combined_prompt_length: number
}

interface DebugPanelProps {
  agent: Agent
  preview: AgentPreview | undefined
  debugTrace: DebugTrace | null
  messages: ChatMessage[]
}

export function DebugPanel({
  agent,
  preview,
  debugTrace,
  messages,
}: DebugPanelProps) {
  const [showPrompt, setShowPrompt] = useState(false)

  return (
    <div className="w-80 flex-shrink-0 overflow-y-auto bg-card border-l border-border h-full">
      <div className="sticky top-0 bg-card border-b border-border px-4 py-3">
        <h2 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">
          Debug Trace
        </h2>
      </div>

      {/* Model Info */}
      <DebugSection title="Model" icon={Cpu}>
        <div className="space-y-1">
          <StatItem label="Primary" value={agent.primary_model_id} />
          {agent.fallback_models.length > 0 && (
            <StatItem
              label="Fallbacks"
              value={agent.fallback_models.join(', ')}
            />
          )}
          <StatItem label="Temperature" value={agent.temperature.toFixed(2)} />
        </div>
      </DebugSection>

      {/* Last Request Stats */}
      {debugTrace && (
        <DebugSection title="Last Request" icon={Zap}>
          <div className="space-y-1">
            <StatItem label="Model Used" value={debugTrace.model_used} />
            <StatItem label="Latency" value={debugTrace.latency_ms} unit="ms" />
            <StatItem label="Input Tokens" value={debugTrace.input_tokens} />
            <StatItem label="Output Tokens" value={debugTrace.output_tokens} />
            <StatItem
              label="Total Tokens"
              value={debugTrace.input_tokens + debugTrace.output_tokens}
            />
          </div>
        </DebugSection>
      )}

      {/* Memory Injection */}
      <DebugSection title="Memory" icon={Tag} defaultOpen={false}>
        <div className="space-y-2">
          {preview && (
            <StatItem label="Injected Count" value={preview.mandate_count} />
          )}
          {debugTrace && debugTrace.mandate_uuids.length > 0 && (
            <div className="mt-2">
              <p className="text-[10px] text-muted-foreground mb-1">UUIDs:</p>
              <div className="space-y-0.5">
                {debugTrace.mandate_uuids.slice(0, 5).map((uuid) => (
                  <p
                    key={uuid}
                    className="text-[10px] font-mono text-muted-foreground truncate"
                  >
                    {uuid}
                  </p>
                ))}
                {debugTrace.mandate_uuids.length > 5 && (
                  <p className="text-[10px] text-muted-foreground">
                    +{debugTrace.mandate_uuids.length - 5} more
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </DebugSection>

      {/* Combined Prompt */}
      <DebugSection title="Combined Prompt" icon={FileText} defaultOpen={false}>
        {preview ? (
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground">Length</span>
              <span className="text-xs font-mono text-foreground">
                {preview.combined_prompt.length} chars
              </span>
            </div>
            <button
              onClick={() => setShowPrompt(!showPrompt)}
              className="text-xs text-amber-500 hover:underline"
            >
              {showPrompt ? 'Hide' : 'Show'} full prompt
            </button>
            {showPrompt && (
              <pre className="mt-2 p-2 rounded bg-muted text-[10px] font-mono text-muted-foreground overflow-x-auto whitespace-pre-wrap max-h-60 overflow-y-auto">
                {preview.combined_prompt}
              </pre>
            )}
          </div>
        ) : (
          <p className="text-xs text-muted-foreground italic">Loading...</p>
        )}
      </DebugSection>

      {/* Token Stats */}
      <DebugSection title="Session Stats" icon={Hash}>
        <div className="space-y-1">
          <StatItem label="Messages" value={messages.length} />
          <StatItem
            label="User Messages"
            value={messages.filter((m) => m.role === 'user').length}
          />
          <StatItem
            label="Assistant Messages"
            value={messages.filter((m) => m.role === 'assistant').length}
          />
        </div>
      </DebugSection>
    </div>
  )
}
