export interface ArenaScheduledJobSummary {
  id: string;
  name: string;
  payload_type: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  run_count: number;
}

export interface ArenaAgentSignalVolume {
  agent_slug: string;
  friction: number;
  improvement: number;
  idea: number;
  praise: number;
  system: number;
}

export interface ArenaRepeatedIssue {
  agent_slug: string;
  feedback_type: string | null;
  content: string;
  count: number;
  latest_at: string | null;
}

export interface ArenaBenchmarkExperimentSignal {
  suite_id: string;
  decision: string;
  decision_reason: string | null;
  score_delta: number;
  pass_rate_delta: number;
}

export interface ArenaOpenRegressionSignal {
  case_id: string;
  occurrence_count: number;
  failure_detail: string;
  failure_kind: string | null;
  failure_category: string | null;
  last_seen_at: string | null;
}

export interface ArenaMemoryUtilizationSummary {
  injection_sessions: number;
  citation_sessions: number;
  lookup_after_injection_sessions: number;
  citation_session_rate: number;
  assistant_citation_rate: number;
  selected_reference_citation_rate: number;
  memory_search_calls: number;
  memory_get_calls: number;
  memory_debug_coverage_rate: number;
}

export interface ArenaReferenceYieldSummary {
  uuid: string;
  label: string;
  selected: number;
  cited: number;
  citation_rate: number;
  tags: string[];
}

export interface ArenaAgentBenchmarkSummary {
  total_runs: number;
  avg_score: number | null;
  pass_rate: number | null;
  open_regressions: number;
  latest_completed_at: string | null;
}

export interface ArenaAgentSummary {
  slug: string;
  name: string;
  description: string | null;
  benchmark: ArenaAgentBenchmarkSummary;
  signal_volume: ArenaAgentSignalVolume | null;
  top_issue: ArenaRepeatedIssue | null;
}

export interface ArenaSystemSummary {
  total_agents: number;
  agents_with_history: number;
  total_runs: number;
  avg_score: number | null;
  avg_pass_rate: number | null;
  total_regressions: number;
}

export interface ArenaOverview {
  generated_at: string;
  project_id: string | null;
  primary_agent_slug: string;
  days: number;
  system: ArenaSystemSummary;
  scheduled_jobs: ArenaScheduledJobSummary[];
  agent_signal_volume: ArenaAgentSignalVolume[];
  repeated_issues: ArenaRepeatedIssue[];
  recent_benchmark_experiments: ArenaBenchmarkExperimentSignal[];
  open_regression_clusters: ArenaOpenRegressionSignal[];
  memory_utilization: ArenaMemoryUtilizationSummary;
  low_yield_references: ArenaReferenceYieldSummary[];
  agents: ArenaAgentSummary[];
}
