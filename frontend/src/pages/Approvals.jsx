import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useLiveEvents } from '../hooks/useLiveEvents'
import { Empty, ErrorNote, Panel, RiskMeter, StatusPill, timeOf } from '../components/ui'

export default function Approvals() {
  const [approvals, setApprovals] = useState([])
  const [error, setError] = useState(null)
  const [notes, setNotes] = useState({})
  const [busy, setBusy] = useState(null)

  const refresh = useCallback(() => {
    api.listApprovals().then(setApprovals).catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  useLiveEvents('/ws/all', refresh)

  const decide = async (id, decision) => {
    setBusy(id)
    setError(null)
    try {
      await api.decideApproval(id, {
        decision,
        decided_by: 'console user',
        note: notes[id] ?? '',
      })
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(null)
    }
  }

  const pending = approvals.filter((a) => a.status === 'pending')
  const resolved = approvals.filter((a) => a.status !== 'pending')

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-50">Approvals</h1>
        <p className="mt-1 text-sm text-slate-400">
          Actions the policy engine held back. Each one has a paused run behind it.
        </p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <Panel title="Waiting on you" description={`${pending.length} pending`}>
        <div aria-live="polite">
          {pending.length === 0 ? (
            <Empty>Nothing is waiting. Agents are running within policy.</Empty>
          ) : (
            <ul className="space-y-3">
              {pending.map((item) => (
                <li key={item.id} className="rounded-xl border border-gate/40 bg-ink-850 p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 text-sm">
                        <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs text-accent">
                          {item.action_type}
                        </code>
                        <span className="truncate text-slate-200">{item.action_label}</span>
                      </p>
                      <p className="mt-1.5 text-sm text-slate-400">{item.rationale}</p>
                      <p className="mt-2 text-xs text-gate">{item.requested_reason}</p>
                      <p className="mt-2 text-xs text-slate-500">
                        Run{' '}
                        <Link to={`/runs/${item.run_id}`} className="text-accent hover:underline">
                          #{item.run_id}
                        </Link>{' '}
                        · {item.run_goal}
                      </p>
                    </div>
                    <RiskMeter score={item.risk_score} />
                  </div>

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <label className="sr-only" htmlFor={`note-${item.id}`}>
                      Note for approval {item.id}
                    </label>
                    <input
                      id={`note-${item.id}`}
                      className="input max-w-xs flex-1"
                      placeholder="Optional note for the audit trail"
                      value={notes[item.id] ?? ''}
                      onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
                    />
                    <button
                      type="button"
                      className="btn-allow"
                      disabled={busy === item.id}
                      onClick={() => decide(item.id, 'approved')}
                    >
                      Approve
                    </button>
                    <button
                      type="button"
                      className="btn-deny"
                      disabled={busy === item.id}
                      onClick={() => decide(item.id, 'denied')}
                    >
                      Deny
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Panel>

      <Panel title="Decision history" description={`${resolved.length} resolved`}>
        {resolved.length === 0 ? (
          <Empty>No decisions recorded yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Previously resolved approval requests</caption>
              <thead>
                <tr className="border-b border-ink-700 text-left text-xs uppercase tracking-wide text-slate-400">
                  <th scope="col" className="py-2 pr-4 font-medium">Action</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Run</th>
                  <th scope="col" className="py-2 pr-4 font-medium">Decision</th>
                  <th scope="col" className="py-2 pr-4 font-medium">By</th>
                  <th scope="col" className="py-2 font-medium">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-800">
                {resolved.map((item) => (
                  <tr key={item.id}>
                    <td className="py-2.5 pr-4">
                      <span className="font-mono text-xs text-slate-400">{item.action_type}</span>{' '}
                      <span className="text-slate-300">{item.action_label}</span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <Link to={`/runs/${item.run_id}`} className="text-accent hover:underline">
                        #{item.run_id}
                      </Link>
                    </td>
                    <td className="py-2.5 pr-4">
                      <StatusPill status={item.status} />
                    </td>
                    <td className="py-2.5 pr-4 text-slate-400">{item.decided_by || '—'}</td>
                    <td className="py-2.5 tabular-nums text-slate-500">{timeOf(item.decided_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}
