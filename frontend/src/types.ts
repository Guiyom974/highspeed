export interface EngineStatus {
  status: 'idle' | 'loading' | 'ready' | 'error' | string
  engine: string | null
  profile: string | null
  requested_profile: string
  device: string | null
  precision: string | null
  calibrated: boolean
  error: string | null
  load_seconds: number | null
  engine_ready: boolean
}

export interface AgreementMetric {
  type: string
  matched: number
  total: number
  agree: number
  agree_strict: number
  levels_used?: number
}

export interface Run {
  id: number
  use_case: string
  status: 'pending' | 'running' | 'done' | 'error' | string
  total: number
  done: number
  progress: number
  message: string
  error: string
  decisions_per_second: number | null
  median_latency_ms: number | null
  agreement: Record<string, AgreementMetric>
  engine: string
  profile: string
  device: string
  calibrated: boolean
  policy_version: number
  scope: Record<string, number>
  started_at: string
  finished_at: string | null
}

export interface UseCaseSummary {
  key: string
  name: string
  industry: string
  monogram: string
  pattern: string
  blurb: string
  disclaimer: string
  question_count: number
  question_types: string[]
  record_count: number
  decision_count: number
  last_run: Run | null
  mean_agreement: number | null
}

export interface Stats {
  use_case_count: number
  total_records: number
  total_decisions: number
  total_answers: number
  questions_per_record: number
  median_latency_ms: number | null
  mean_latency_ms: number | null
  best_throughput: number | null
  runs_completed: number
  engine: EngineStatus
  running: Run | null
  busy: boolean
  policy?: PolicySummary
  use_cases: UseCaseSummary[]
}

export type Criteria = Record<string, string> | string[]

export interface Question {
  type: 'boolean' | 'noul' | 'choice' | 'score' | string
  instructions: string
  criteria?: Criteria
}

export interface Answer {
  type: string
  value: string | boolean | number
  p_true?: number
  confidence?: number | null
  confidence_calibrated?: number
  p_true_calibrated?: number
  adjustment?: string
  scope_note?: string
  routing?: string
  probabilities?: Record<string, number>
  choice?: string
  score?: number
  level?: number
}

export interface DecisionData {
  run: number
  answers: Record<string, Answer>
  latency_ms: number | null
  engine: string
  profile: string
  device: string
}

export interface RecRow {
  id: number
  ref: string
  payload: Record<string, unknown>
  ground_truth: Record<string, unknown>
  decision: DecisionData | null
}

export interface UseCaseDetail {
  summary: UseCaseSummary
  questions: Record<string, Question>
  truth_map: Record<string, string>
  display_fields: [string, string][]
  primary_field: string
  records: RecRow[]
  runs: Run[]
}

export interface PolicySummary {
  version: number
  gates: { act_gate: number; floor: number }
  criteria_enabled: boolean
  materiality_enabled: boolean
  use_case_overrides: number
  apply_calibration: boolean
}

export interface CriteriaParams {
  enabled: boolean
  match_mode: 'any' | 'all'
  must_contain: string[]
  must_not_contain: string[]
  fuzzy: boolean
  min_similarity: number
}

export interface MaterialityParams {
  enabled: boolean
  field: string
  min_amount: number
  review_amount: number
}

export interface UseCaseOverride {
  gates?: { act_gate?: number; floor?: number }
  criteria?: Partial<CriteriaParams>
  materiality?: Partial<MaterialityParams>
}

export interface PolicyParams {
  gates: { act_gate: number; floor: number }
  criteria: CriteriaParams
  materiality: MaterialityParams
  learning: { apply_calibration: boolean; act_target_precision: number }
  use_cases: Record<string, UseCaseOverride>
}

export interface PolicyConfigRow {
  version: number
  is_active: boolean
  params: PolicyParams
  note: string
  created_by: string
  created_at: string
}

export interface PolicyResponse {
  active: PolicyConfigRow
  versions: PolicyConfigRow[]
  merged: PolicyParams
  write_roles: string[]
  governance_key_required: boolean
}

export interface FeedbackRow {
  id: number
  record: number
  use_case: string
  ref: string
  question_id: string
  model_value: unknown
  model_confidence: number | null
  human_value: unknown
  source: string
  actor: string
  note: string
  created_at: string
}

export interface CalibrationBin {
  lo: number
  hi: number
  n: number
  acc: number | null
}

export interface CalibrationScope {
  scope: string
  use_case: string
  question_id: string
  question_type: string
  n_samples: number
  n_human: number
  fitted: boolean
  bins: CalibrationBin[]
  bias: Record<string, unknown>
  accuracy_raw: number | null
  accuracy_calibrated: number | null
  ece_raw: number | null
  ece_calibrated: number | null
  fitted_at: string | null
  history: { at: string; n: number; ece_raw: number | null; ece_calibrated: number | null }[]
}

export interface LearningSuggestion {
  param: string
  current: number
  suggested: number
  rationale: string
  n: number
}

export interface LearningData {
  min_samples: number
  feedback_count: number
  scopes: CalibrationScope[]
  by_use_case: {
    use_case: string
    questions: number
    fitted: number
    n_samples: number
    n_human: number
    ece_raw: number | null
    ece_calibrated: number | null
  }[]
  recent_feedback: FeedbackRow[]
  policy_version: number
  gates: { act_gate: number; floor: number }
  apply_calibration: boolean
  suggestions: { suggestions: LearningSuggestion[]; basis: Record<string, unknown> }
  export_url: string
}
