import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Run, Stats } from '../types'
import { pct } from '../format'
import KpiRow from '../components/KpiRow'
import UseCaseCard from '../components/UseCaseCard'
import Panel from '../components/Panel'

interface Props {
  stats: Stats | null
  onStats: (stats: Stats) => void
  onOpen: (key: string) => void
}

export default function OverviewPage({ stats, onStats, onOpen }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [filterText, setFilterText] = useState('')
  const [filterIndustry, setFilterIndustry] = useState('all')

  const load = useCallback(async () => {
    try {
      onStats(await api.stats())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'backend unreachable — is launcher.bat running?')
    }
  }, [onStats])

  useEffect(() => { void load() }, [load])

  const busy = stats?.busy ?? false
  useEffect(() => {
    if (!busy && stats?.engine.status !== 'loading') return
    const id = window.setInterval(() => { void load() }, 1500)
    return () => window.clearInterval(id)
  }, [busy, stats?.engine.status, load])

  useEffect(() => {
    if (!notice) return
    const id = window.setTimeout(() => setNotice(null), 7000)
    return () => window.clearTimeout(id)
  }, [notice])

  const startRun = async (key: string, limit?: number) => {
    setError(null)
    setNotice(null)
    try {
      const run: Run = await api.run(key, limit)
      setNotice(`Run #${run.id} started${limit ? ` (${limit} records)` : ''} — one batched pass per record.`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not start run')
    }
  }

  const runAll = async () => {
    setError(null)
    setNotice(null)
    try {
      const res = await api.runAll()
      setNotice(`Full sweep queued: ${res.started} use cases, sequential on the warm engine.`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'could not start sweep')
    }
  }

  const reseed = async () => {
    if (!window.confirm('Regenerate all 12 synthetic datasets? Decisions and runs are wiped.')) return
    try {
      const res = await api.reseed()
      setNotice(`Reseeded ${res.records} records (deterministic, seed 20260926).`)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'reseed failed')
    }
  }

  const running = stats?.running

  const industries = Array.from(new Set((stats?.use_cases ?? []).map((u) => u.industry))).sort()
  const q = filterText.trim().toLowerCase()
  const visible = (stats?.use_cases ?? []).filter((u) =>
    (filterIndustry === 'all' || u.industry === filterIndustry) &&
    (!q || u.name.toLowerCase().includes(q) || u.key.includes(q) ||
     u.industry.toLowerCase().includes(q) || u.pattern.toLowerCase().includes(q) ||
     u.blurb.toLowerCase().includes(q)))
  const answersPerSweep = (stats?.use_cases ?? []).reduce(
    (sum, u) => sum + u.record_count * u.question_count, 0)

  return (
    <>
      {error && <div className="banner error" role="alert"><b>Backend:</b> {error}</div>}
      {notice && <div className="banner ok" role="status">{notice}</div>}

      {stats?.engine.status === 'loading' && (
        <div className="banner warn">
          <span className="spinner dark" />
          Warming the decision engine ({stats.engine.requested_profile}) — first load takes ~10–30 s,
          then every run reuses the warm model. Browse the datasets meanwhile.
        </div>
      )}
      {stats?.engine.status === 'error' && (
        <div className="banner error">
          <b>Engine error:</b> {stats.engine.error}. Set <code>SYSTEMONE_PROFILE=cpu-nli</code> if this
          machine has no CUDA GPU, and check <code>SYSTEMONE_MODELS_DIR</code> points at the
          folder where you downloaded the openjev weights (see <code>models/README.md</code>).
        </div>
      )}

      <KpiRow stats={stats} />

      {running && (running.status === 'running' || running.status === 'pending') && (
        <div className="toolbar glass">
          <div className="progress-wrap" style={{ flex: 1 }}>
            <div className="progress shimmer">
              <span style={{ width: `${Math.round((running.progress || 0) * 100)}%` }} />
            </div>
            <span className="progress-text num">
              {running.use_case} · {running.done}/{running.total} · {pct(running.progress)}
            </span>
          </div>
          <button className="btn ghost sm" onClick={() => onOpen(running.use_case)}>Open use case</button>
        </div>
      )}

      <div className="toolbar glass">
        <div className="toolbar-group">
          <button className="btn primary" onClick={() => void runAll()} disabled={busy}
                  title={`Run all ${stats?.use_case_count ?? 0} use cases sequentially on the warm engine`}>
            {busy ? <span className="spinner" /> : null}
            {busy ? 'Running…' : `Run full sweep (${stats?.use_case_count ?? 0} use cases)`}
          </button>
          <button className="btn ghost danger" onClick={() => void reseed()} disabled={busy}
                  title="Regenerate every synthetic dataset (deterministic seed)">
            Reseed datasets
          </button>
        </div>
        <div className="toolbar-spacer" />
        <span className="cell-sub">
          {stats ? `${stats.total_records.toLocaleString('en-US')} records · ~${answersPerSweep.toLocaleString('en-US')} typed answers per sweep · ` : ''}
          all decisions local, offline, $0 marginal cost
        </span>
      </div>

      <div className="toolbar glass filter-bar">
        <div className="toolbar-group">
          <label className="sr-only" htmlFor="uc-filter">Filter use cases</label>
          <input id="uc-filter" className="input search" placeholder="Filter use cases…"
                 value={filterText} onChange={(e) => setFilterText(e.target.value)} />
          <label className="sr-only" htmlFor="uc-industry">Industry</label>
          <select id="uc-industry" className="select" value={filterIndustry}
                  onChange={(e) => setFilterIndustry(e.target.value)}>
            <option value="all">All industries</option>
            {industries.map((ind) => <option key={ind} value={ind}>{ind}</option>)}
          </select>
        </div>
        <div className="toolbar-spacer" />
        <span className="cell-sub num">
          {visible.length} / {stats?.use_case_count ?? 0} shown
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="card glass">
          <div className="empty">
            <h3>No use cases match the filter</h3>
            <p>Clear the search text or pick “All industries”.</p>
          </div>
        </div>
      ) : (
        <div className="uc-grid">
          {visible.map((s) => (
            <UseCaseCard key={s.key} summary={s} busy={busy}
                         onOpen={onOpen} onRun={(k, limit) => void startRun(k, limit)} />
          ))}
        </div>
      )}

      <div className="info-cols">
        <Panel title="Why System One" subtitle="decisions, not strings" defaultOpen={false}>
          <div className="prose">
            <p>
              <b>Jev-class System One models</b> (TypeSafe's Jev; open-source OpenJev — this demo runs
              the MIT-licensed <code>openjev-nli</code> 0.8B locally) answer <b>typed questions</b> about
              a state instead of generating text: <code>boolean</code>, <code>choice</code> (2–64
              options), <code>score</code> (2–10 ordered levels). The answer <i>shape is the API
              contract</i> — nothing to parse, no off-schema output, no prompt-injection surface in
              the response.
            </p>
            <p>
              <b>Batch economics:</b> the state is ingested once and every question is scored in the
              same pass — 10–20 questions cost about one call. This repo measured a 13-question
              payload <b>10× faster / 12× cheaper</b> than sequential calls. A generative LLM
              classifier call typically takes 1.5–15 s and per-token fees; the warm local engine here
              answers in the tens-to-hundreds of milliseconds per record (measured, top-right), with
              <b>$0 marginal cost, offline, on your hardware</b>.
            </p>
            <p className="cell-sub">
              Sources: docs.typesafe.ai/introduction · jevtypesafe.org · openjev.tech ·
              systemonemodels.org · langchain.com/blog/building-a-harness-with-jev.
            </p>
          </div>
        </Panel>

        <Panel title="Honest limits" subtitle="when NOT to use it" defaultOpen={false}>
          <div className="prose">
            <ul>
              <li><b>No generation</b> — System One decides; System 2 (an LLM) still writes the reply, the code, the summary.</li>
              <li><b>No multi-hop reasoning</b> — hard-tier inference is where small models bleed accuracy; keep questions to snap judgments.</li>
              <li><b>Uncalibrated local confidence</b> — hosted Jev is RLCD-calibrated; the local NLI engine returns raw softmax (act gate 0.90, review floor 0.50). Validate ECE on your own traffic before raising automation thresholds.</li>
              <li><b>English-only engine here</b> — non-Latin text routes to the multilingual/hosted profile.</li>
              <li><b>Agreement numbers</b> on this site are measured against <i>designed synthetic labels</i> — they demonstrate the mechanics, not a benchmark.</li>
              <li>Caps: ≤32 states/request, ≤96 questions/request, ≤64 options, 4096-token context.</li>
            </ul>
          </div>
        </Panel>
      </div>

      <div className="footer-note">
        HighSpeed · synthetic data only · decisions by a local MIT-licensed System One model
        {stats?.engine.engine && (
          <> (<code>{stats.engine.engine}</code> on <code>{stats.engine.device ?? 'cpu'}</code>)</>
        )}
        {' · '}warm singleton, batched payloads · no per-decision API cost
      </div>
    </>
  )
}
