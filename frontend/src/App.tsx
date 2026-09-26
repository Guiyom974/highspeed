import { useCallback, useState } from 'react'
import { api } from './api'
import type { Stats } from './types'
import TopBar from './components/TopBar'
import OverviewPage from './pages/OverviewPage'
import UseCasePage from './pages/UseCasePage'
import GovernancePage from './pages/GovernancePage'

export default function App() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [view, setView] = useState<
    { name: 'overview' } | { name: 'usecase'; key: string } | { name: 'governance' }
  >({ name: 'overview' })

  const onStats = useCallback((s: Stats) => setStats(s), [])

  const runAll = async () => {
    try {
      await api.runAll()
      if (stats) setStats({ ...stats, busy: true })
    } catch {
      /* overview surfaces the error banner on next poll */
    }
  }

  return (
    <div className="shell">
      <div className="mesh-bg" aria-hidden="true" />
      <TopBar
        engine={stats?.engine ?? null}
        busy={stats?.busy ?? false}
        canRun={view.name === 'overview'}
        governanceActive={view.name === 'governance'}
        onHome={() => setView({ name: 'overview' })}
        onGovernance={() => setView({ name: 'governance' })}
        onRunAll={() => void runAll()}
      />
      <main className="content">
        {view.name === 'overview' ? (
          <OverviewPage stats={stats} onStats={onStats}
                        onOpen={(key) => setView({ name: 'usecase', key })} />
        ) : view.name === 'governance' ? (
          <GovernancePage onBack={() => setView({ name: 'overview' })} />
        ) : (
          <UseCasePage useCaseKey={view.key} onBack={() => setView({ name: 'overview' })} />
        )}
      </main>
    </div>
  )
}
