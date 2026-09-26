import type { Stats } from '../types'
import { ms, num, pct } from '../format'

function Kpi({ label, value, foot, tone, small, accent }: {
  label: string
  value: string
  foot?: string
  tone?: string
  small?: boolean
  accent?: boolean
}) {
  return (
    <div className={`kpi glass${tone ? ` ${tone}` : ''}${accent ? ' accent' : ''}`}>
      <div className="kpi-label">{label}</div>
      <div className={`kpi-value num${small ? ' small' : ''}`}>{value}</div>
      {foot && <div className="kpi-foot">{foot}</div>}
    </div>
  )
}

export default function KpiRow({ stats }: { stats: Stats | null }) {
  if (!stats) {
    return (
      <div className="kpi-grid">
        {Array.from({ length: 6 }).map((_, i) => (
          <div className="kpi glass skeleton" key={i}>
            <div className="kpi-label">loading</div><div className="kpi-value">—</div>
          </div>
        ))}
      </div>
    )
  }
  const answered = stats.use_cases.filter((u) => u.decision_count > 0).length
  const agreements = stats.use_cases.map((u) => u.mean_agreement).filter((v): v is number => v !== null)
  const meanAgree = agreements.length ? agreements.reduce((a, b) => a + b, 0) / agreements.length : null

  return (
    <div className="kpi-grid">
      <Kpi label="Use cases" value={String(stats.use_case_count)}
           foot={`${answered}/${stats.use_case_count} decided · ${stats.questions_per_record} questions/record avg`} />
      <Kpi label="Synthetic records" value={String(stats.total_records)}
           foot="seeded · deterministic · ground-truth labelled" />
      <Kpi label="Typed answers" value={stats.total_answers.toLocaleString('en-US')}
           foot={`${stats.total_decisions} batched decisions`} accent />
      <Kpi label="Median latency" value={ms(stats.median_latency_ms)} tone="teal"
           foot={`amortized per record · mean ${ms(stats.mean_latency_ms)}`} />
      <Kpi label="Best throughput" value={stats.best_throughput ? `${num(stats.best_throughput, 2)}/s` : '—'}
           tone="green" foot={`${stats.runs_completed} completed run(s)`} />
      <Kpi label="Mean agreement" value={pct(meanAgree)} tone={meanAgree !== null && meanAgree >= 0.8 ? 'green' : 'amber'}
           foot="vs designed synthetic labels (indicative)" />
    </div>
  )
}
