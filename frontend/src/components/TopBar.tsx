import type { EngineStatus } from '../types'

function engineLabel(engine: EngineStatus): string {
  if (engine.engine) return engine.engine === 'openjev-nli' ? 'openjev NLI 0.8B' : engine.engine
  return engine.requested_profile || 'System One'
}

function statusText(engine: EngineStatus): string {
  switch (engine.status) {
    case 'ready':
      return engine.load_seconds ? `ready · ${engine.load_seconds.toFixed(0)}s load` : 'ready'
    case 'loading':
      return 'warming up…'
    case 'error':
      return 'engine error'
    default:
      return 'idle'
  }
}

interface Props {
  engine: EngineStatus | null
  busy: boolean
  onHome: () => void
  onRunAll: () => void
  onGovernance: () => void
  canRun: boolean
  governanceActive: boolean
}

export default function TopBar({ engine, busy, onHome, onRunAll, onGovernance, canRun,
                                 governanceActive }: Props) {
  return (
    <header className="topbar glass-bar">
      <button className="brand brand-btn" onClick={onHome} title="Back to overview">
        <div className="brand-mark" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 32 32" aria-hidden="true">
            <path d="M18.5 4 9 18h5l-2.5 10L23 13h-5.5L18.5 4Z" fill="currentColor" />
          </svg>
        </div>
        <div style={{ textAlign: 'left' }}>
          <div className="brand-name">HighSpeed</div>
          <div className="brand-sub">System One decision showcase · local · MIT models</div>
        </div>
      </button>

      <div className="topbar-spacer" />

      {engine && (
        <div className="engine-badge" title={engine.error || 'Decision engine status'}>
          <span className={`dot ${engine.status === 'ready' ? 'ready' : engine.status === 'error' ? 'error' : 'loading'}`} />
          <span>
            <b>{engineLabel(engine)}</b>
            {engine.device ? ` · ${engine.device.toUpperCase()}` : ''}
          </span>
          <span className="muted">{statusText(engine)}</span>
          {engine.status === 'ready' && !engine.calibrated && (
            <span className="chip slate" title="Raw softmax confidence — gates configured per act 0.90 / floor 0.50">
              uncalibrated
            </span>
          )}
        </div>
      )}

      <button className={`btn sm${governanceActive ? ' primary' : ' ghost'}`} onClick={onGovernance}
              title="Governance: policy parameters, match criteria, materiality, learning">
        Governance
      </button>

      {canRun && (
        <button className="btn primary" onClick={onRunAll} disabled={busy}
                title="Run all 62 use cases sequentially on the warm engine">
          {busy ? <span className="spinner" /> : null}
          {busy ? 'Sweeping…' : 'Run full sweep'}
        </button>
      )}
    </header>
  )
}
