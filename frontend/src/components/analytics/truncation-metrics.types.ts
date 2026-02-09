export interface TruncationAggregation {
  group_key: string;
  truncation_count: number;
  avg_output_tokens: number;
  avg_max_tokens: number;
  capped_count: number;
}

export interface TruncationMetrics {
  aggregations: TruncationAggregation[];
  total_truncations: number;
  truncation_rate: number;
  recent_events: Array<{
    id: number;
    model: string;
    endpoint: string;
    output_tokens: number;
    max_tokens_requested: number;
    model_limit: number;
    was_capped: boolean;
    created_at: string;
  }>;
}

export interface TruncationMetricsWidgetProps {
  className?: string;
  compact?: boolean;
  days?: number;
}

export type SeverityLevel = "low" | "medium" | "high";

export interface SeverityStyles {
  bg: string;
  border: string;
  accent: string;
  glow: string;
}
