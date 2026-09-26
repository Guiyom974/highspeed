import type {
  EngineStatus, FeedbackRow, LearningData, PolicyConfigRow, PolicyParams,
  PolicyResponse, Run, Stats, UseCaseDetail, UseCaseSummary,
} from './types'

export const identity = {
  get role(): string {
    return sessionStorage.getItem('hs_role') || 'viewer'
  },
  set role(value: string) {
    sessionStorage.setItem('hs_role', value)
  },
  get actor(): string {
    return sessionStorage.getItem('hs_actor') || ''
  },
  set actor(value: string) {
    sessionStorage.setItem('hs_actor', value)
  },
}

function governanceHeaders(): Record<string, string> {
  return { 'X-Role': identity.role, 'X-Actor': identity.actor }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? 'GET').toUpperCase()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(governanceHeaders()),
    ...(init?.headers as Record<string, string> | undefined),
  }
  const response = await fetch(path, { credentials: 'same-origin', ...init, method, headers })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body?.error || body?.detail || JSON.stringify(body).slice(0, 200)
    } catch {
      /* keep the status text */
    }
    throw new Error(detail)
  }
  return (await response.json()) as T
}

export const api = {
  stats: () => request<Stats>('/api/stats'),
  engine: () => request<EngineStatus>('/api/engine'),
  useCases: () => request<UseCaseSummary[]>('/api/usecases'),
  useCase: (key: string) => request<UseCaseDetail>(`/api/usecases/${key}`),
  run: (key: string, limit?: number) =>
    request<Run>(`/api/usecases/${key}/run`, {
      method: 'POST',
      body: JSON.stringify(limit ? { limit } : {}),
    }),
  runAll: () => request<{ started: number; runs: Run[] }>('/api/runs/all', {
    method: 'POST',
    body: JSON.stringify({}),
  }),
  runDetail: (id: number) => request<Run>(`/api/runs/${id}`),
  latestRun: (useCase?: string, runningOnly = false) => {
    const params = new URLSearchParams()
    if (useCase) params.set('use_case', useCase)
    if (runningOnly) params.set('running', '1')
    const qs = params.toString()
    return request<Run | Record<string, never>>(`/api/runs/latest${qs ? `?${qs}` : ''}`)
  },
  reseed: (seed?: number) =>
    request<{ reseeded: boolean; records: number }>('/api/actions/reseed', {
      method: 'POST',
      body: JSON.stringify(seed ? { seed } : {}),
    }),
  policy: () => request<PolicyResponse>('/api/policy'),
  savePolicy: (params: PolicyParams, note: string) =>
    request<PolicyConfigRow>('/api/policy', {
      method: 'POST',
      body: JSON.stringify({ params, note }),
    }),
  activatePolicy: (version: number) =>
    request<PolicyConfigRow>(`/api/policy/activate/${version}`, {
      method: 'POST',
      body: JSON.stringify({}),
    }),
  feedback: (useCase?: string) =>
    request<{ count: number; results: FeedbackRow[] }>(
      `/api/feedback${useCase ? `?use_case=${encodeURIComponent(useCase)}` : ''}`),
  submitFeedback: (recordId: number, questionId: string, value: unknown, note?: string) =>
    request<{ feedback: FeedbackRow; calibration: Record<string, unknown> }>('/api/feedback', {
      method: 'POST',
      body: JSON.stringify({ record_id: recordId, question_id: questionId, value, note }),
    }),
  learning: (useCase?: string) =>
    request<LearningData>(`/api/learning${useCase ? `?use_case=${encodeURIComponent(useCase)}` : ''}`),
  refit: (useCase?: string) =>
    request<{ fitted: number; metrics: LearningData }>('/api/learning/refit', {
      method: 'POST',
      body: JSON.stringify(useCase ? { use_case: useCase } : {}),
    }),
  applyLearning: (params: PolicyParams | null, note: string) =>
    request<PolicyConfigRow>('/api/learning/apply', {
      method: 'POST',
      body: JSON.stringify({ params, note }),
    }),
}

export const exportUrl = (key: string) => `/api/usecases/${key}/export.csv`
export const learningExportUrl = '/api/learning/export'
