import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Empty, ErrorNote, Panel, Stat, money } from '../components/ui'

export default function Spend() {
  const [summary, setSummary] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    api.spendSummary().then(setSummary).catch((e) => setError(e.message))
  }, [])

  const rows = summary?.by_run ?? []
  const peak = Math.max(1, ...rows.map((r) => r.cost_usd))

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-50">Model spend</h1>
        <p className="mt-1 text-sm text-slate-400">
          Token usage and cost for every planning call, attributed to the run that made it.
        </p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Total cost" value={money(summary?.total_usd ?? 0)} hint="all runs" />
        <Stat label="Planner calls" value={summary?.calls ?? 0} hint="requests to the model" />
        <Stat
          label="Input tokens"
          value={(summary?.total_input_tokens ?? 0).toLocaleString()}
          hint="page context and history"
        />
        <Stat
          label="Output tokens"
          value={(summary?.total_output_tokens ?? 0).toLocaleString()}
          hint="planned actions"
        />
      </div>

      <Panel title="Cost by run" description="Most recent runs first">
        {rows.length === 0 ? (
          <Empty>No planner calls recorded yet.</Empty>
        ) : (
          <ul className="space-y-2">
            {rows.map((row) => (
              <li key={row.run_id} className="flex items-center gap-3">
                <Link
                  to={`/runs/${row.run_id}`}
                  className="w-16 shrink-0 font-mono text-xs text-accent hover:underline"
                >
                  #{row.run_id}
                </Link>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-ink-800">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${Math.max(2, (row.cost_usd / peak) * 100)}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right text-xs tabular-nums text-slate-400">
                  {money(row.cost_usd)}
                </span>
                <span className="w-20 shrink-0 text-right text-xs tabular-nums text-slate-600">
                  {row.calls} calls
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
