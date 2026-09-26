import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, exportUrl, identity } from '../api'
import type { RecRow, Run, UseCaseDetail } from '../types'
import {
  RUN_STATUS_TONE, TYPE_TONE, answerLabel, answerTone, ms, num, pct, probColor, titleCase, tone, when,
} from '../format'
import Panel from '../components/Panel'
import Pagination from '../components/Pagination'

const PAGE_SIZE = 12

const LABEL_ROLES = new Set(['analyst', 'compliance', 'admin'])

interface Props {
  useCaseKey: string
  onBack: () => void
}

function AnswerCell({ row, qid, detail }: { row: RecRow; qid: string; detail: UseCaseDetail }) {
  const [open, setOpen] = useState(false)
  const [humanValue, setHumanValue] = useState<unknown>(null)
  const [labelStatus, setLabelStatus] = useState<string | null>(null)
  const [labelError, setLabelError] = useState<string | null>(null)
  const [savingLabel, setSavingLabel] = useState(false)
  const answer = row.decision?.answers?.[qid]
  const question = detail.questions[qid]
  if (!answer) return <span className="cell-sub">—</span>
  const truthKey = detail.truth_map[qid]
  const truth = truthKey ? row.ground_truth[truthKey] : undefined
  let match: boolean | null = null
  if (truth !== undefined) {
    if (question.type === 'boolean' || question.type === 'noul') {
      match = Boolean(answer.value) === Boolean(truth)
    } else if (question.type === 'choice') {
      match = String(answer.value) === String(truth)
    } else {
      const level = answer.level ?? Math.round(Number(answer.value ?? 0))
      match = Math.abs(level - Number(truth)) <= 1
    }
  }
  const probs = Object.entries(answer.probabilities ?? {})
  const canLabel = LABEL_ROLES.has(identity.role)

  const submitLabel = async (value: unknown) => {
    setSavingLabel(true)
    setLabelError(null)
    try {
      const res = await api.submitFeedback(row.id, qid, value)
      setHumanValue(res.feedback.human_value)
      setLabelStatus(res.calibration.fitted
        ? `saved · calibrator refit (n=${String(res.calibration.n_samples)})`
        : 'saved · fits once 10 labelled pairs exist')
    } catch (e) {
      setLabelError(e instanceof Error ? e.message : 'could not save label')
    } finally {
      setSavingLabel(false)
    }
  }

  return (
    <div className="answer-cell">
      <button type="button" className="answer-main" onClick={() => setOpen((v) => !v)}
              aria-expanded={open} title={probs.length ? 'Show probability distribution' : undefined}>
        <span className={`chip ${answerTone(answer)}`}>{answerLabel(answer, question)}</span>
        {match !== null && (
          <span className={`match-dot ${match ? 'ok' : 'bad'}`}
                title={match ? 'matches designed ground truth' : 'differs from designed ground truth'}>
            {match ? '✓' : '✗'}
          </span>
        )}
        {answer.confidence != null && (
          <span className="cell-sub num conf">{pct(answer.confidence)}</span>
        )}
        {answer.confidence_calibrated != null && (
          <span className="cell-sub num conf cal"
                title="calibrated confidence from fitted reliability map">
            {pct(answer.confidence_calibrated)}
          </span>
        )}
        {probs.length > 0 && <span className="cell-sub expand-hint">{open ? '▾' : '▸'}</span>}
      </button>
      {(answer.adjustment || answer.scope_note || humanValue !== null) && (
        <div className="answer-flags">
          {answer.adjustment && (
            <span className="chip amber" title="learned correction applied by the fitted calibrator">
              learned
            </span>
          )}
          {answer.scope_note && (
            <span className="chip slate" title={answer.scope_note}>scope</span>
          )}
          {humanValue !== null && (
            <span className="chip green" title="human label saved — feeds the calibrator">
              human: {String(humanValue)}
            </span>
          )}
        </div>
      )}
      {open && (
        <div className="prob-detail">
          {probs.map(([k, v], i) => (
            <div key={k} className="prob-row">
              <span className="prob-key">{k}</span>
              <span className="prob-track"><i style={{ width: `${Math.max(v * 100, 0.5)}%`, background: probColor(i) }} /></span>
              <span className="num cell-sub">{pct(v, 1)}</span>
            </div>
          ))}
          {answer.routing && (
            <div className="cell-sub" style={{ marginTop: 4 }}>
              routing: <span className={`chip ${tone(RUN_STATUS_TONE, answer.routing === 'act' ? 'done' : answer.routing === 'review' ? 'running' : 'pending')}`}>{answer.routing}</span>
              {answer.p_true != null && <> · p_true {num(answer.p_true, 3)}</>}
              {answer.p_true_calibrated != null && <> · cal {num(answer.p_true_calibrated, 3)}</>}
            </div>
          )}
          {answer.scope_note && (
            <div className="cell-sub" style={{ marginTop: 4 }}>{answer.scope_note}</div>
          )}
          {canLabel && (
            <div className="human-label">
              <div className="cell-sub">Human label (HITL — corrects the calibrator):</div>
              {question.type === 'boolean' || question.type === 'noul' ? (
                <div className="toolbar-group">
                  <button className="btn sm" disabled={savingLabel}
                          onClick={() => void submitLabel(true)}>Mark YES</button>
                  <button className="btn sm" disabled={savingLabel}
                          onClick={() => void submitLabel(false)}>Mark NO</button>
                </div>
              ) : question.type === 'choice' ? (
                <select disabled={savingLabel} value=""
                        onChange={(e) => e.target.value && void submitLabel(e.target.value)}>
                  <option value="">choose correct option…</option>
                  {Object.keys(question.criteria ?? {}).map((opt) => (
                    <option key={opt} value={opt}>{opt}</option>
                  ))}
                </select>
              ) : (
                <select disabled={savingLabel} value=""
                        onChange={(e) => e.target.value !== '' && void submitLabel(Number(e.target.value))}>
                  <option value="">choose correct level…</option>
                  {(Array.isArray(question.criteria) ? question.criteria : []).map((lvl, i) => (
                    <option key={i} value={i}>{i} · {lvl}</option>
                  ))}
                </select>
              )}
              {labelStatus && <div className="cell-sub ok-text">{labelStatus}</div>}
              {labelError && <div className="cell-sub err-text">{labelError}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function UseCasePage({ useCaseKey, onBack }: Props) {
  const [detail, setDetail] = useState<UseCaseDetail | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const [tab, setTab] = useState<'results' | 'dataset'>('results')

  const load = useCallback(async () => {
    try {
      setDetail(await api.useCase(useCaseKey))
      const latest = await api.latestRun(useCaseKey)
      setRun(Object.keys(latest).length ? (latest as Run) : null)
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not load use case')
    }
  }, [useCaseKey])

  useEffect(() => { void load(); setOffset(0); setTab('results') }, [load])

  const running = run !== null && (run.status === 'running' || run.status === 'pending')
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(async () => {
      try {
        const latest = await api.latestRun(useCaseKey)
        if (Object.keys(latest).length) {
          const r = latest as Run
          setRun(r)
          if (r.status === 'done' || r.status === 'error') await load()
        }
      } catch { /* transient */ }
    }, 1200)
    return () => window.clearInterval(id)
  }, [running, useCaseKey, load])

  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 7000)
    return () => window.clearTimeout(id)
  }, [notice])

  const startRun = async (limit?: number) => {
    setError(null)
    try {
      const r = await api.run(useCaseKey, limit)
      setRun(r)
      setNotice(`Run #${r.id} started${limit ? ` on ${limit} records` : ''}.`)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not start run')
    }
  }

  const decidedRows = useMemo(() => detail?.records.filter((r) => r.decision) ?? [], [detail])
  const tableRows = tab === 'results' && decidedRows.length ? decidedRows : detail?.records ?? []
  const viewRows = tableRows.slice(offset, offset + PAGE_SIZE)

  if (!detail) {
    return (
      <>
        {error && <div className="banner error" role="alert">{error}</div>}
        <div className="card glass"><div className="empty"><h3>Loading use case…</h3></div></div>
      </>
    )
  }

  const s = detail.summary
  const qids = Object.keys(detail.questions)
  const lastDone = detail.runs.find((r) => r.status === 'done') ?? null
  const agreement = lastDone?.agreement ?? {}

  return (
    <>
      {error && <div className="banner error" role="alert">{error}</div>}
      {notice && <div className="banner ok" role="status">{notice}</div>}

      <div className="uc-header card glass">
        <button className="btn ghost sm" onClick={onBack}>‹ All use cases</button>
        <div className="uc-head" style={{ marginTop: 8 }}>
          <div className="uc-mono lg" aria-hidden="true">{s.monogram}</div>
          <div className="uc-title">
            <h2>{s.name}</h2>
            <div className="uc-meta">
              <span className="chip indigo">{s.industry}</span>
              <span className="chip slate">{s.pattern}</span>
              <span className="cell-sub">{qids.length} typed questions · {s.record_count} synthetic records</span>
            </div>
          </div>
          <div className="uc-actions" style={{ marginLeft: 'auto' }}>
            <button className="btn sm" disabled={running} onClick={() => void startRun(10)}>Quick run 10</button>
            <button className="btn primary sm" disabled={running} onClick={() => void startRun()}>
              {running ? <span className="spinner" /> : null}
              Run all {s.record_count}
            </button>
            <a className="btn sm" href={exportUrl(useCaseKey)}
               title="Export decisions with ground truth and per-question match flags">Export CSV</a>
          </div>
        </div>
        <p className="uc-blurb" style={{ marginTop: 10 }}>{s.blurb}</p>
        {s.disclaimer && <div className="banner warn" style={{ marginTop: 10 }}>{s.disclaimer}</div>}

        {run && (running || run.status === 'error') && (
          <div className="progress-wrap" style={{ marginTop: 12 }}>
            <div className={`progress${running ? ' shimmer' : ''}`}>
              <span style={{ width: `${run.status === 'error' ? 100 : Math.round((run.progress || 0) * 100)}%` }} />
            </div>
            <span className="progress-text num">
              {run.status === 'error' ? `failed: ${run.error.slice(0, 80)}` : `${run.done}/${run.total} · ${pct(run.progress)}`}
            </span>
          </div>
        )}

        {lastDone && (
          <div className="metric-strip">
            <div className="metric"><span className="metric-k">throughput</span>
              <span className="metric-v num">{num(lastDone.decisions_per_second, 2)}/s</span></div>
            <div className="metric"><span className="metric-k">median latency</span>
              <span className="metric-v num">{ms(lastDone.median_latency_ms)}</span></div>
            <div className="metric"><span className="metric-k">engine</span>
              <span className="metric-v">{lastDone.engine || '—'}{lastDone.device ? ` · ${lastDone.device}` : ''}</span></div>
            <div className="metric"><span className="metric-k">finished</span>
              <span className="metric-v">{when(lastDone.finished_at)}</span></div>
            {!lastDone.calibrated && lastDone.engine && (
              <span className="chip slate" title="Raw softmax confidence; act gate 0.90 / floor 0.50">uncalibrated</span>
            )}
          </div>
        )}
      </div>

      <div className="detail-cols">
        <div className="detail-main">
          <section className="card glass">
            <div className="card-head">
              <div className="toolbar-group" style={{ gap: 4 }}>
                <button className={`btn sm${tab === 'results' ? ' primary' : ' ghost'}`} onClick={() => { setTab('results'); setOffset(0) }}>
                  Results {decidedRows.length > 0 && <span className="count num">{decidedRows.length}</span>}
                </button>
                <button className={`btn sm${tab === 'dataset' ? ' primary' : ' ghost'}`} onClick={() => { setTab('dataset'); setOffset(0) }}>
                  Dataset <span className="count num">{detail.records.length}</span>
                </button>
              </div>
              <div className="toolbar-spacer" />
              <div className="card-sub">
                {tab === 'results'
                  ? decidedRows.length
                    ? 'typed answers · confidence · routing · ✓/✗ vs designed ground truth (click an answer for probabilities)'
                    : 'no decisions yet — run the use case'
                  : 'synthetic records with the designed ground-truth labels'}
              </div>
            </div>

            {viewRows.length === 0 ? (
              <div className="empty">
                <h3>{tab === 'results' ? 'Nothing decided yet' : 'Dataset empty'}</h3>
                <p>{tab === 'results'
                  ? 'Press “Run all” (or Quick run 10) to send every record through the warm System One engine in batched payloads.'
                  : 'Reseed the datasets from the overview page.'}</p>
              </div>
            ) : (
              <div className="table-wrap results-wrap">
                <table className="grid">
                  <thead>
                    <tr>
                      <th style={{ width: 110 }}>Ref</th>
                      {detail.display_fields.map(([field, label]) => (
                        <th key={field}>{label}</th>
                      ))}
                      <th>Input</th>
                      {qids.map((qid) => <th key={qid}>{titleCase(qid)}</th>)}
                      <th style={{ width: 90, textAlign: 'right' }}>Latency</th>
                    </tr>
                  </thead>
                  <tbody>
                    {viewRows.map((row) => (
                      <tr key={row.id}>
                        <td className="mono cell-sub">{row.ref}</td>
                        {detail.display_fields.map(([field]) => (
                          <td key={field} className="cell-sub">
                            {field === detail.primary_field ? '' : String(row.payload[field] ?? '')}
                          </td>
                        ))}
                        <td className="input-cell" title={String(row.payload[detail.primary_field] ?? '')}>
                          {String(row.payload[detail.primary_field] ?? '').slice(0, 150)}
                        </td>
                        {qids.map((qid) => (
                          <td key={qid}>
                            {tab === 'dataset'
                              ? <TruthChip qid={qid} truth={row.ground_truth[detail.truth_map[qid]]} question={detail.questions[qid]} />
                              : <AnswerCell row={row} qid={qid} detail={detail} />}
                          </td>
                        ))}
                        <td className="num cell-sub" style={{ textAlign: 'right' }}>
                          {tab === 'results' ? ms(row.decision?.latency_ms) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
          <Pagination count={tableRows.length} limit={PAGE_SIZE} offset={offset} onOffset={setOffset} />
        </div>

        <div className="detail-side">
          <Panel title="Decision schema" subtitle={`${qids.length} typed questions, one batched pass`}>
            <div className="schema-list">
              {qids.map((qid) => {
                const q = detail.questions[qid]
                const crit = q.criteria
                return (
                  <div key={qid} className="schema-item">
                    <div className="schema-head">
                      <span className={`chip ${tone(TYPE_TONE, q.type)}`}>{q.type}</span>
                      <b>{qid}</b>
                      {agreement[qid] && (
                        <span className={`chip ${agreement[qid].agree >= 0.8 ? 'green' : agreement[qid].agree >= 0.6 ? 'amber' : 'red'}`}
                              title={`${agreement[qid].matched}/${agreement[qid].total} within tolerance vs designed labels`}>
                          {pct(agreement[qid].agree)}{agreement[qid].type === 'score' ? ' ±1' : ''}
                        </span>
                      )}
                      {agreement[qid]?.agree_strict !== undefined && agreement[qid].type !== 'boolean' && (
                        <span className="chip slate" title="Exact-match agreement (no tolerance)">
                          {pct(agreement[qid].agree_strict)} exact
                        </span>
                      )}
                      {agreement[qid]?.levels_used !== undefined && agreement[qid].levels_used! <= 1 && (
                        <span className="chip red" title="The model predicted a single level for every record — the tolerant number above hides a constant predictor">
                          degenerate
                        </span>
                      )}
                    </div>
                    <div className="cell-sub">{q.instructions}</div>
                    {Array.isArray(crit) ? (
                      <ol className="schema-crit">
                        {crit.map((lvl, i) => <li key={i}>{lvl}</li>)}
                      </ol>
                    ) : crit ? (
                      <ul className="schema-crit">
                        {Object.entries(crit).map(([k, v]) => <li key={k}><b>{k}</b> — {v}</li>)}
                      </ul>
                    ) : null}
                    {agreement[qid] && (
                      <div className="agree-bar" title="agreement with designed synthetic ground truth">
                        <span style={{ width: pct(agreement[qid].agree) }} />
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </Panel>

          <Panel title="Run history" badge={<span className="count num">{detail.runs.length}</span>} defaultOpen={false}>
            {detail.runs.length === 0 ? (
              <div className="cell-sub">No runs yet.</div>
            ) : (
              <ul className="run-list">
                {detail.runs.map((r) => (
                  <li key={r.id} className={r.status === 'done' ? 'ok' : r.status === 'error' ? 'bad' : ''}>
                    <div className="run-head">
                      <span className={`chip ${tone(RUN_STATUS_TONE, r.status)}`}>{r.status}</span>
                      <b className="num">#{r.id}</b>
                      <span className="cell-sub">{r.done}/{r.total}</span>
                      <span className="cell-sub num" style={{ marginLeft: 'auto' }}>{when(r.started_at)}</span>
                    </div>
                    {r.status === 'done' && (
                      <div className="cell-sub num">
                        {num(r.decisions_per_second, 2)}/s · median {ms(r.median_latency_ms)} · {r.engine || '—'}
                      </div>
                    )}
                    {r.status === 'error' && <div className="cell-sub">{r.error.slice(0, 120)}</div>}
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>
    </>
  )
}

function TruthChip({ qid, truth, question }: { qid: string; truth: unknown; question: { type: string; criteria?: Record<string, string> | string[] } }) {
  if (truth === undefined || truth === null) return <span className="cell-sub">—</span>
  let label: string
  if (question.type === 'boolean' || question.type === 'noul') label = truth ? 'YES' : 'NO'
  else if (question.type === 'score') {
    const levels = Array.isArray(question.criteria) ? question.criteria : []
    label = `${truth} · ${(levels[Number(truth)] ?? '').split(/[.:]/)[0]}`
  } else label = titleCase(String(truth))
  void qid
  return <span className="chip truth">{label}</span>
}
