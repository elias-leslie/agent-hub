export interface PersonaImprovementSchedule {
  job_id: string | null
  enabled: boolean
  schedule_type: string
  schedule_value: string
  schedule_timezone: string
  cadence_minutes: number
  cadence_label: string | null
  last_run_at: string | null
  next_run_at: string | null
  run_count: number
}

export interface PersonaImprovementOverview {
  total_runs: number
  latest_completed_at: string | null
  reliability: number | null
  effectiveness: number | null
  tokens_per_passed_attempt: number | null
  prompt_tokens: number | null
  open_regressions: number
}

export interface PersonaImprovementTrendPoint {
  run_id: string
  completed_at: string | null
  run_kind: string
  suite_id: string
  reliability: number | null
  effectiveness: number | null
  avg_total_tokens: number | null
  tokens_per_passed_attempt: number | null
  avg_tool_calls: number | null
  avg_turns: number | null
  prompt_tokens: number | null
}

export interface PersonaImprovementFamilySummary {
  family: string
  attempts: number
  pass_rate: number
  productive_attempts: number
}

export interface PersonaImprovementRecentRun {
  run_id: string
  benchmark_id: string
  suite_id: string
  run_kind: string
  started_at: string
  completed_at: string | null
  models: string[]
  case_ids: string[]
  attempt_count: number
  passed_attempt_count: number
  infra_failure_count: number
  reliability: number | null
  effectiveness: number | null
  avg_total_tokens: number | null
  tokens_per_passed_attempt: number | null
  avg_tool_calls: number | null
  avg_turns: number | null
  prompt_tokens: number | null
  failure_count: number | null
  top_failure_detail: string | null
  family_breakdown: PersonaImprovementFamilySummary[]
  experiment_decision: string | null
  experiment_decision_reason: string | null
  decision_source: string | null
}

export interface PersonaImprovementOpenRegression {
  case_id: string
  failure_detail: string
  occurrence_count: number
  last_seen_at: string | null
  latest_avg_score: number | null
}

export interface PersonaHeartbeatFieldOverview {
  total_heartbeats: number
  latest_completed_at: string | null
  reliability: number | null
  effectiveness: number | null
  truth_quality: number | null
  tokens_per_healthy_heartbeat: number | null
  avg_tool_calls: number | null
  avg_turns: number | null
  healthy_heartbeats: number
  healthy_rate: number | null
  risky_heartbeats: number
  critical_heartbeats: number
  action_heartbeats: number
  action_rate: number | null
  ok_heartbeats: number
  ok_rate: number | null
  partial_heartbeats: number
  partial_rate: number | null
  completed_heartbeats: number
  failed_heartbeats: number
  unknown_heartbeats: number
  top_issue_code: string | null
  top_issue_label: string | null
  top_issue_count: number
}

export interface PersonaHeartbeatFieldTrendPoint {
  session_id: string
  completed_at: string | null
  reliability: number | null
  effectiveness: number | null
  truth_quality: number | null
  total_tokens: number
  tool_calls: number
  turns: number
  result_status: string
}

export interface PersonaHeartbeatFieldRisk {
  session_id: string
  completed_at: string | null
  reliability: number | null
  issue_summary: string
  summary_oneliner: string | null
  critical: boolean
}

export interface PersonaImprovementScheduleRisk {
  kind: string
  summary: string
  detail: string | null
  critical: boolean
}

export interface PersonaHeartbeatFieldSession {
  session_id: string
  completed_at: string
  created_at: string
  status: string
  result_status: string
  summary_oneliner: string | null
  reliability: number
  effectiveness: number
  truth_quality: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
  tool_calls: number
  turns: number
  issue_codes: string[]
  issue_summary: string
  healthy: boolean
}

export interface PersonaHeartbeatFieldReviewGate {
  needs_review: boolean
  reason_codes: string[]
  summary: string
}

export interface PersonaImprovementDashboard {
  generated_at: string
  suite_id: string
  days: number
  schedule: PersonaImprovementSchedule
  overview: PersonaImprovementOverview
  latest_lab_run: PersonaImprovementRecentRun | null
  field_overview: PersonaHeartbeatFieldOverview
  field_window_days: number
  field_window_lab_runs: number
  field_review_gate: PersonaHeartbeatFieldReviewGate
  trend: PersonaImprovementTrendPoint[]
  field_trend: PersonaHeartbeatFieldTrendPoint[]
  recent_runs: PersonaImprovementRecentRun[]
  recent_heartbeats: PersonaHeartbeatFieldSession[]
  open_regressions: PersonaImprovementOpenRegression[]
  field_risks: PersonaHeartbeatFieldRisk[]
  schedule_risks: PersonaImprovementScheduleRisk[]
}

export interface PersonaImprovementScheduleUpdate {
  enabled: boolean
  cadence_minutes: number
}
