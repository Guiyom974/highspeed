import type { UseCaseSummary } from '../types'
import { RUN_STATUS_TONE, pct, tone, titleCase } from '../format'

interface Props {
  summary: UseCaseSummary
  busy: boolean
  onOpen: (key: string) => void
  onRun: (key: string, limit?: number) => void
}

export default function UseCaseCard({ summary, busy, onOpen, onRun }: Props) {
  const s = summary
  const last = s.last_run
  const running = last && (last.status === 'running' || last.status === 'pending')
  const decided = s.decision_count > 0

  return (
    <article className={`uc-card glass${running ? ' running' : ''}`} onClick={() => onOpen(s.key)}>
      <header className="uc-head">
        <div className="uc-mono" aria-hidden="true">{s.monogram}</div>
        <div className="uc-title">
          <h3>{s.name}</h3>
          <div className="uc-meta">
            <span className="chip indigo">{s.industry}</span>
            <span className="chip slate">{s.pattern}</span>
          </div>
        </div>
      </header>

      <p className="uc-blurb">{s.blurb}</p>

      <div className="uc-types">
        {s.question_types.map((t) => (
          <span key={t} className="chip type-chip">{titleCase(t)}</span>
        ))}
        <span className="cell-sub">{s.question_count} typed questions · {s.record_count} records</span>
      </div>

      <footer className="uc-foot">
        {last ? (
          <span className={`chip ${tone(RUN_STATUS_TONE, last.status)}`}>
            {running ? `running ${last.done}/${last.total}` : last.status === 'done' ? 'decided' : last.status}
          </span>
        ) : (
          <span className="chip slate">not run yet</span>
        )}
        {decided && s.mean_agreement !== null && (
          <span className={`chip ${s.mean_agreement >= 0.8 ? 'green' : 'amber'}`}
                title="Mean agreement with the designed synthetic ground truth">
            {pct(s.mean_agreement)} agree
          </span>
        )}
        {decided && last?.decisions_per_second != null && (
          <span className="chip teal">{last.decisions_per_second.toFixed(2)}/s</span>
        )}
        <div className="uc-actions" onClick={(e) => e.stopPropagation()}>
          <button className="btn sm" disabled={busy || !!running}
                  onClick={() => onRun(s.key, 10)} title="Decide 10 records on the warm engine">
            Quick run
          </button>
          <button className="btn primary sm" disabled={busy || !!running}
                  onClick={() => onRun(s.key)} title={`Decide all ${s.record_count} records`}>
            Run {s.record_count}
          </button>
        </div>
      </footer>
    </article>
  )
}
