import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useLiveEvents } from '../hooks/useLiveEvents'
import { Empty, ErrorNote, Panel, Stat, StatusPill, money, timeOf } from '../components/ui'

const PRESETS = [
  {
    label: 'Book a vendor meeting',
    goal: 'Find Acme Industrial Supply in the vendor directory and book a meeting with them for next Tuesday morning. Use the name "Ada Lovelace" and email "ada@northwind.example".',
  },
  {
    label: 'Delete a vendor (gets blocked)',
    goal: 'Corva Components is no longer a supplier. Open their account settings from the vendor directory and permanently delete their account.',
  },
  {
    label: 'Pay an outstanding invoice',
    goal: 'Go to the invoices page and pay invoice INV-2043 in full.',
  },
  {
    label: 'Summarise open invoices',
    goal: 'Read the invoices page and report how many invoices are outstanding and their total value.',
  },
]

export default function Dashboard() {
  const navigate = useNavigate()
  const [agents, setAgents] = useState([])
  const [runs, setRuns] = useState([])
  const [stats, setStats] = useState(null)
  const [form, setForm] = useState({ agent_id: '', goal: '', start_url: '/demo/index.html' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const refresh = useCallback(() => {
    api.listRuns().then(setRuns).catch((e) => setError(e.message))
    api.stats().then(setStats).catch(() => {})
  }, [])

  useEffect(() => {
    api
      .listAgents()
      .then((list) => {
        setAgents(list)
        setForm((f) => ({ ...f, agent_id: f.agent_id || String(list[0]?.id ?? '') }))
      })
      .catch((e) => setError(e.message))
    refresh()
  }, [refresh])

  useLiveEvents('/ws/all', refresh)

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const startUrl = form.start_url.startsWith('/')
        ? `${window.location.origin}${form.start_url}`
        : form.start_url
      const run = await api.createRun({
        agent_id: Number(form.agent_id),
        goal: form.goal.trim(),
        start_url: startUrl,
      })
      navigate(`/runs/${run.id}`)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const byStatus = stats?.runs_by_status ?? {}
  const activeRuns = (byStatus.running ?? 0) + (byStatus.awaiting_approval ?? 0)

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-50">Overview</h1>
        <p className="mt-1 text-sm text-slate-400">
          Give an AI employee a goal. Every action it proposes is checked against policy before it
          touches the browser.
        </p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Active runs" value={activeRuns} hint="running or waiting on a human" />
        <Stat label="Awaiting approval" value={stats?.pending_approvals ?? 0} hint="in the queue now" />
        <Stat label="Completed" value={byStatus.completed ?? 0} hint="finished successfully" />
        <Stat label="Model spend" value={money(stats?.total_spend_usd ?? 0)} hint="across all runs" />
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Panel
          title="Start a run"
          description="The agent plans one step at a time; you stay in control of the risky ones."
          className="lg:col-span-2"
        >
          <form onSubmit={submit} className="space-y-4">
            <div>
              <label className="label" htmlFor="agent">
                Agent
              </label>
              <select
                id="agent"
                className="input"
                value={form.agent_id}
                onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
                required
              >
                {agents.map((agent) => (
                  <option key={agent.id} value={agent.id}>
                    {agent.name} — {agent.role}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="label" htmlFor="goal">
                Goal
              </label>
              <textarea
                id="goal"
                className="input min-h-[92px] resize-y"
                placeholder="What should the agent accomplish?"
                value={form.goal}
                onChange={(e) => setForm({ ...form, goal: e.target.value })}
                required
                minLength={3}
              />
              <div className="mt-2 flex flex-wrap gap-1.5">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    onClick={() => setForm({ ...form, goal: preset.goal })}
                    className="rounded-full border border-ink-700 px-2.5 py-1 text-xs text-slate-400 hover:bg-ink-800 hover:text-slate-200"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="label" htmlFor="start-url">
                Starting page
              </label>
              <input
                id="start-url"
                className="input font-mono text-xs"
                value={form.start_url}
                onChange={(e) => setForm({ ...form, start_url: e.target.value })}
              />
              <p className="mt-1.5 text-xs text-slate-500">
                Defaults to the bundled sandbox portal so you can demo safely.
              </p>
            </div>

            <button type="submit" className="btn-primary w-full" disabled={busy || !agents.length}>
              {busy ? 'Starting…' : 'Start governed run'}
            </button>
          </form>
        </Panel>

        <Panel title="Recent runs" description="Newest first" className="lg:col-span-3">
          {runs.length === 0 ? (
            <Empty>No runs yet. Start one to see the governance trail.</Empty>
          ) : (
            <ul className="divide-y divide-ink-800">
              {runs.slice(0, 10).map((run) => (
                <li key={run.id}>
                  <button
                    type="button"
                    onClick={() => navigate(`/runs/${run.id}`)}
                    className="flex w-full items-start gap-3 rounded-lg px-2 py-3 text-left hover:bg-ink-850"
                  >
                    <span className="mt-0.5 font-mono text-xs text-slate-500">#{run.id}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-slate-200">{run.goal}</span>
                      <span className="mt-1 block text-xs text-slate-500">
                        {timeOf(run.created_at)}
                        {run.summary ? ` · ${run.summary}` : ''}
                      </span>
                    </span>
                    <StatusPill status={run.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}
