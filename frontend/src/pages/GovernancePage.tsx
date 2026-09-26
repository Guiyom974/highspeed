import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, identity, learningExportUrl } from '../api'
import type {
  LearningData, PolicyParams, PolicyResponse, UseCaseOverride, UseCaseSummary,
} from '../types'
import { num, pct, when } from '../format'

interface Props {
  onBack: () => void
}

const ROLES = ['viewer', 'analyst', 'compliance', 'admin'] as const

function toList(text: string): string[] {
  return text.split(/[,\n]/).map((t) => t.trim()).filter(Boolean)
}

function fromList(list: string[] | undefined): string {
  return (list ?? []).join('\n')
}

function biasLabel(bias: Record<string, unknown>): string {
  const parts: string[] = []
  if (typeof bias.p_shift === 'number') parts.push(`p-shift ${bias.p_shift >= 0 ? '+' : ''}${num(bias.p_shift, 3)}`)
  if (typeof bias.score_offset === 'number') parts.push(`level offset ${bias.score_offset >= 0 ? '+' : ''}${num(bias.score_offset, 2)}`)
  if (bias.choice_map && typeof bias.choice_map === 'object') {
    parts.push(`choice map ×${Object.keys(bias.choice_map as object).length}`)
  }
  return parts.length ? parts.join(' · ') : '—'
}

export default function GovernancePage({ onBack }: Props) {
  const [policyRes, setPolicyRes] = useState<PolicyResponse | null>(null)
  const [params, setParams] = useState<PolicyParams | null>(null)
  const [learning, setLearning] = useState<LearningData | null>(null)
  const [useCases, setUseCases] = useState<UseCaseSummary[]>([])
  const [note, setNote] = useState('')
  const [role, setRole] = useState(identity.role)
  const [actor, setActor] = useState(identity.actor)
  const [overrideKey, setOverrideKey] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [busy, setBusy] = useState(false)

  const canWrite = role === 'compliance' || role === 'admin'

  const load = useCallback(async () => {
    try {
      const [pol, lrn, ucs] = await Promise.all([api.policy(), api.learning(), api.useCases()])
      setPolicyRes(pol)
      setParams(structuredClone(pol.merged))
      setLearning(lrn)
      setUseCases(ucs)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not load governance state')
    }
  }, [])

  useEffect(() => { void load() }, [load])

  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 7000)
    return () => window.clearTimeout(id)
  }, [notice])

  const patch = (fn: (draft: PolicyParams) => void) => {
    setParams((prev) => {
      if (!prev) return prev
      const next = structuredClone(prev)
      fn(next)
      return next
    })
  }

  const savePolicy = async () => {
    if (!params) return
    setSaving(true)
    setError(null)
    try {
      const saved = await api.savePolicy(params, note || 'manual edit')
      setNotice(`Policy v${saved.version} saved and activated (${saved.created_by}).`)
      setNote('')
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'save failed')
    } finally {
      setSaving(false)
    }
  }

  const activate = async (version: number) => {
    setBusy(true)
    setError(null)
    try {
      await api.activatePolicy(version)
      setNotice(`Rolled back to policy v${version}.`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'activate failed')
    } finally {
      setBusy(false)
    }
  }

  const refit = async () => {
    setBusy(true)
    setError(null)
    try {
      const res = await api.refit()
      setNotice(`Refit complete: ${res.fitted} calibrator(s) fitted.`)
      setLearning(res.metrics)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'refit failed')
    } finally {
      setBusy(false)
    }
  }

  const applySuggestion = async () => {
    setBusy(true)
    setError(null)
    try {
      const saved = await api.applyLearning(null, 'learning auto-tune (act gate)')
      setNotice(`Suggestion applied as policy v${saved.version}.`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'apply failed')
    } finally {
      setBusy(false)
    }
  }

  const override = useMemo<UseCaseOverride>(() => {
    if (!params || !overrideKey) return {}
    return params.use_cases[overrideKey] ?? {}
  }, [params, overrideKey])

  const setOverride = (fn: (draft: UseCaseOverride) => void) => {
    patch((draft) => {
      const entry = draft.use_cases[overrideKey] ?? {}
      const next = structuredClone(entry)
      fn(next)
      draft.use_cases[overrideKey] = next
    })
  }

  const clearOverride = () => {
    patch((draft) => { delete draft.use_cases[overrideKey] })
    setNotice(`Override cleared for ${overrideKey} (save to commit).`)
  }

  if (!params || !policyRes) {
    return (
      <div className="card glass">
        <div className="empty"><h3>Loading governance…</h3></div>
      </div>
    )
  }

  const sugg = learning?.suggestions.suggestions ?? []
  const fittedScopes = learning?.scopes.filter((c) => c.fitted) ?? []
  const meanEceRaw = fittedScopes.length
    ? fittedScopes.reduce((a, c) => a + (c.ece_raw ?? 0), 0) / fittedScopes.length
    : null
  const meanEceCal = fittedScopes.length
    ? fittedScopes.reduce((a, c) => a + (c.ece_calibrated ?? 0), 0) / fittedScopes.length
    : null

  return (
    <>
      {error && <div className="banner error" role="alert">{error}</div>}
      {notice && <div className="banner ok" role="status">{notice}</div>}

      <div className="card glass">
        <div className="card-head">
          <button className="btn ghost sm" onClick={onBack}>‹ Overview</button>
          <div className="toolbar-spacer" />
          <div className="card-sub">
            leadership / compliance parameters · policy v{policyRes.active.version} active ·
            calibrated gates {num(params.gates.act_gate, 2)} / {num(params.gates.floor, 2)}
          </div>
        </div>
        <div className="gov-identity">
          <label className="gov-field">
            <span>Governance role (X-Role header)</span>
            <select value={role}
                    onChange={(e) => { setRole(e.target.value); identity.role = e.target.value }}>
              {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <label className="gov-field">
            <span>Actor name (X-Actor, attributed on saves)</span>
            <input value={actor} placeholder="e.g. a.compliance"
                   onChange={(e) => { setActor(e.target.value); identity.actor = e.target.value }} />
          </label>
          <div className="cell-sub" style={{ maxWidth: 520 }}>
            Writes require compliance/admin ({policyRes.write_roles.join(' / ')})
            {policyRes.governance_key_required ? ' plus X-Governance-Key' : ''}.
            {' '}This showcase uses advisory headers — production deployments put these routes
            behind real auth/RBAC (FastKYC ships that reference).
          </div>
        </div>
      </div>

      <div className="gov-cols">
        <section className="card glass">
          <div className="card-head">
            <span className="card-title">Decision policy</span>
            <span className="card-sub">gates · match criteria · materiality</span>
          </div>
          <div className="gov-body">
            <div className="gov-section">
              <b>Confidence gates</b>
              <div className="gov-grid">
                <label className="gov-field">
                  <span>act gate (calibrated conf ≥ → auto)</span>
                  <input type="number" step="0.01" min="0" max="1" value={params.gates.act_gate}
                         onChange={(e) => patch((d) => { d.gates.act_gate = Number(e.target.value) })} />
                </label>
                <label className="gov-field">
                  <span>review floor (below → fallback)</span>
                  <input type="number" step="0.01" min="0" max="1" value={params.gates.floor}
                         onChange={(e) => patch((d) => { d.gates.floor = Number(e.target.value) })} />
                </label>
                <label className="gov-field check">
                  <input type="checkbox" checked={params.learning.apply_calibration}
                         onChange={(e) => patch((d) => { d.learning.apply_calibration = e.target.checked })} />
                  <span>apply fitted calibration to confidence &amp; values</span>
                </label>
                <label className="gov-field">
                  <span>act-gate suggestion target (precision)</span>
                  <input type="number" step="0.01" min="0.5" max="1"
                         value={params.learning.act_target_precision}
                         onChange={(e) => patch((d) => { d.learning.act_target_precision = Number(e.target.value) })} />
                </label>
              </div>
            </div>

            <div className="gov-section">
              <b>Search / match criteria</b>
              <div className="gov-grid">
                <label className="gov-field check">
                  <input type="checkbox" checked={params.criteria.enabled}
                         onChange={(e) => patch((d) => { d.criteria.enabled = e.target.checked })} />
                  <span>criteria active (out-of-scope records route “excluded”)</span>
                </label>
                <label className="gov-field">
                  <span>must-contain match mode</span>
                  <select value={params.criteria.match_mode}
                          onChange={(e) => patch((d) => { d.criteria.match_mode = e.target.value as 'any' | 'all' })}>
                    <option value="any">any term</option>
                    <option value="all">all terms</option>
                  </select>
                </label>
                <label className="gov-field check">
                  <input type="checkbox" checked={params.criteria.fuzzy}
                         onChange={(e) => patch((d) => { d.criteria.fuzzy = e.target.checked })} />
                  <span>fuzzy similarity instead of substring</span>
                </label>
                <label className="gov-field">
                  <span>min similarity (fuzzy, 0–1)</span>
                  <input type="number" step="0.05" min="0" max="1"
                         value={params.criteria.min_similarity}
                         onChange={(e) => patch((d) => { d.criteria.min_similarity = Number(e.target.value) })} />
                </label>
                <label className="gov-field wide">
                  <span>must contain (one per line)</span>
                  <textarea rows={3} value={fromList(params.criteria.must_contain)}
                            onChange={(e) => patch((d) => { d.criteria.must_contain = toList(e.target.value) })} />
                </label>
                <label className="gov-field wide">
                  <span>must not contain (one per line)</span>
                  <textarea rows={3} value={fromList(params.criteria.must_not_contain)}
                            onChange={(e) => patch((d) => { d.criteria.must_not_contain = toList(e.target.value) })} />
                </label>
              </div>
            </div>

            <div className="gov-section">
              <b>Materiality</b>
              <div className="gov-grid">
                <label className="gov-field check">
                  <input type="checkbox" checked={params.materiality.enabled}
                         onChange={(e) => patch((d) => { d.materiality.enabled = e.target.checked })} />
                  <span>materiality active (below floor → auto-dispose)</span>
                </label>
                <label className="gov-field">
                  <span>payload field</span>
                  <input value={params.materiality.field} placeholder="e.g. amount_usd"
                         onChange={(e) => patch((d) => { d.materiality.field = e.target.value })} />
                </label>
                <label className="gov-field">
                  <span>min amount (below → not material)</span>
                  <input type="number" min="0" value={params.materiality.min_amount}
                         onChange={(e) => patch((d) => { d.materiality.min_amount = Number(e.target.value) })} />
                </label>
                <label className="gov-field">
                  <span>review amount (≥ → forced human review, 0 = off)</span>
                  <input type="number" min="0" value={params.materiality.review_amount}
                         onChange={(e) => patch((d) => { d.materiality.review_amount = Number(e.target.value) })} />
                </label>
              </div>
            </div>

            <div className="gov-section">
              <b>Per-use-case override</b>
              <div className="gov-grid">
                <label className="gov-field">
                  <span>use case</span>
                  <select value={overrideKey} onChange={(e) => setOverrideKey(e.target.value)}>
                    <option value="">— none —</option>
                    {useCases.map((uc) => (
                      <option key={uc.key} value={uc.key}>
                        {uc.name}{params.use_cases[uc.key] ? ' · overridden' : ''}
                      </option>
                    ))}
                  </select>
                </label>
                {overrideKey && (
                  <>
                    <label className="gov-field">
                      <span>act gate override (blank = inherit)</span>
                      <input type="number" step="0.01" min="0" max="1"
                             placeholder={String(params.gates.act_gate)}
                             value={override.gates?.act_gate ?? ''}
                             onChange={(e) => setOverride((d) => {
                               d.gates = { ...d.gates, ...(e.target.value === '' ? { act_gate: undefined } : { act_gate: Number(e.target.value) }) }
                             })} />
                    </label>
                    <label className="gov-field check">
                      <input type="checkbox" checked={override.criteria?.enabled ?? false}
                             onChange={(e) => setOverride((d) => {
                               d.criteria = { ...d.criteria, enabled: e.target.checked }
                             })} />
                      <span>criteria on for this use case</span>
                    </label>
                    <label className="gov-field wide">
                      <span>must contain override (one per line)</span>
                      <textarea rows={2} value={fromList(override.criteria?.must_contain)}
                                onChange={(e) => setOverride((d) => {
                                  d.criteria = { ...d.criteria, must_contain: toList(e.target.value) }
                                })} />
                    </label>
                    <label className="gov-field">
                      <span>materiality field override</span>
                      <input value={override.materiality?.field ?? ''}
                             placeholder={params.materiality.field || 'e.g. amount_usd'}
                             onChange={(e) => setOverride((d) => {
                               d.materiality = { ...d.materiality, field: e.target.value }
                             })} />
                    </label>
                    <div className="toolbar-group">
                      <button className="btn sm" onClick={clearOverride}>Clear override</button>
                      <span className="cell-sub">then Save policy to commit</span>
                    </div>
                  </>
                )}
              </div>
            </div>

            <div className="gov-save">
              <label className="gov-field" style={{ flex: 1 }}>
                <span>Change note (audit trail / version history)</span>
                <input value={note} placeholder="e.g. Q4 materiality raise for payments"
                       onChange={(e) => setNote(e.target.value)} />
              </label>
              <button className="btn primary" disabled={!canWrite || saving}
                      title={canWrite ? 'Save as a new policy version' : 'switch to compliance/admin role'}
                      onClick={() => void savePolicy()}>
                {saving ? <span className="spinner" /> : null}
                Save as new version
              </button>
            </div>
            {!canWrite && (
              <div className="cell-sub">Read-only for role “{role}” — switch to compliance/admin to save.</div>
            )}
          </div>
        </section>

        <div className="gov-side">
          <section className="card glass">
            <div className="card-head">
              <span className="card-title">Policy versions</span>
              <span className="card-sub">immutable · rollback = activate</span>
            </div>
            <div className="gov-body">
              <ul className="run-list">
                {policyRes.versions.map((v) => (
                  <li key={v.version} className={v.is_active ? 'ok' : ''}>
                    <div className="run-head">
                      <b className="num">v{v.version}</b>
                      {v.is_active && <span className="chip green">active</span>}
                      <span className="cell-sub">{v.created_by || 'system'}</span>
                      <span className="cell-sub" style={{ marginLeft: 'auto' }}>{when(v.created_at)}</span>
                    </div>
                    <div className="cell-sub">{v.note || '—'}</div>
                    {!v.is_active && (
                      <button className="btn sm" disabled={!canWrite || busy}
                              onClick={() => void activate(v.version)}>Activate</button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </section>

          <section className="card glass">
            <div className="card-head">
              <span className="card-title">Self-learning loop</span>
              <span className="card-sub">HITL labels → calibrated gates</span>
            </div>
            <div className="gov-body">
              <div className="metric-strip">
                <div className="metric">
                  <span className="metric-k">human labels</span>
                  <span className="metric-v num">{learning?.feedback_count ?? 0}</span>
                </div>
                <div className="metric">
                  <span className="metric-k">fitted scopes</span>
                  <span className="metric-v num">
                    {fittedScopes.length}/{learning?.scopes.length ?? 0}
                  </span>
                </div>
                <div className="metric">
                  <span className="metric-k">ECE raw → cal</span>
                  <span className="metric-v num">
                    {meanEceRaw !== null ? `${num(meanEceRaw, 3)} → ${num(meanEceCal ?? 0, 3)}` : '—'}
                  </span>
                </div>
              </div>

              {sugg.length > 0 ? (
                <div className="gov-suggestion">
                  {sugg.map((s) => (
                    <div key={s.param}>
                      <div className="cell-sub">
                        <b>{s.param}</b>: {num(s.current, 2)} → <b>{num(s.suggested, 2)}</b>
                        {' '}(n={s.n})
                      </div>
                      <div className="cell-sub">{s.rationale}</div>
                    </div>
                  ))}
                  <button className="btn primary sm" disabled={!canWrite || busy}
                          onClick={() => void applySuggestion()}>
                    Apply as new policy version
                  </button>
                </div>
              ) : (
                <div className="cell-sub">
                  No gate suggestion right now{learning?.suggestions.basis.reason
                    ? ` — ${String(learning.suggestions.basis.reason)}`
                    : '. Fit calibrators (run + refit) to enable auto-tuning.'}
                </div>
              )}

              <div className="toolbar-group" style={{ marginTop: 8 }}>
                <button className="btn sm" disabled={!canWrite || busy} onClick={() => void refit()}>
                  {busy ? <span className="spinner" /> : null} Refit calibrators
                </button>
                <a className="btn sm" href={learningExportUrl}
                   title="JSONL of (state, question, model answer, human label) for offline fine-tuning">
                  Export fine-tune dataset
                </a>
              </div>

              {fittedScopes.length > 0 && (
                <div className="table-wrap" style={{ marginTop: 10 }}>
                  <table className="grid">
                    <thead>
                      <tr>
                        <th>Scope</th>
                        <th style={{ textAlign: 'right' }}>n</th>
                        <th style={{ textAlign: 'right' }}>human</th>
                        <th style={{ textAlign: 'right' }}>ECE</th>
                        <th>Bias</th>
                      </tr>
                    </thead>
                    <tbody>
                      {fittedScopes.slice(0, 12).map((c) => (
                        <tr key={c.scope}>
                          <td className="mono cell-sub">{c.scope}</td>
                          <td className="num cell-sub" style={{ textAlign: 'right' }}>{c.n_samples}</td>
                          <td className="num cell-sub" style={{ textAlign: 'right' }}>{c.n_human}</td>
                          <td className="num cell-sub" style={{ textAlign: 'right' }}>
                            {num(c.ece_raw ?? 0, 3)} → {num(c.ece_calibrated ?? 0, 3)}
                          </td>
                          <td className="cell-sub">{biasLabel(c.bias)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {(learning?.recent_feedback.length ?? 0) > 0 && (
                <>
                  <div className="card-sub" style={{ marginTop: 12 }}>Recent human labels</div>
                  <ul className="run-list">
                    {learning?.recent_feedback.slice(0, 8).map((f) => (
                      <li key={f.id}>
                        <div className="cell-sub">
                          <b className="mono">{f.use_case}/{f.ref}</b> · {f.question_id}: model{' '}
                          <span className="chip slate">{String(f.model_value)}</span> → human{' '}
                          <span className="chip green">{String(f.human_value)}</span>
                        </div>
                        <div className="cell-sub">{f.actor || 'human'} · {when(f.created_at)} · {pct(f.model_confidence ?? 0)}</div>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
