import { useEffect, useState } from 'react'
import { api } from '../api'
import { EffectBadge, Empty, ErrorNote, Panel, RiskMeter } from '../components/ui'

const ACTIONS = [
  'read_page',
  'navigate',
  'click',
  'type',
  'select',
  'submit',
  'scroll',
  'download',
  'purchase',
]

const SCENARIOS = [
  { label: 'Read a page', action_type: 'read_page', params: {} },
  { label: 'Open an unknown site', action_type: 'navigate', params: { url: 'https://unknown-supplier.io' } },
  { label: 'Type a card number', action_type: 'type', params: { label: 'Card number', text: '4111 1111 1111 1111' } },
  { label: 'Submit a form', action_type: 'submit', params: { label: 'Send meeting request' } },
  { label: 'Spend $750', action_type: 'purchase', params: { label: 'Confirm order', amount_usd: 750 } },
  { label: 'Spend $9,000', action_type: 'purchase', params: { label: 'Confirm order', amount_usd: 9000 } },
]

export default function Policies() {
  const [policies, setPolicies] = useState([])
  const [selected, setSelected] = useState(null)
  const [error, setError] = useState(null)
  const [form, setForm] = useState({ action_type: 'click', label: '', url: '', amount: '', page_url: '' })
  const [result, setResult] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .listPolicies()
      .then((list) => {
        setPolicies(list)
        setSelected(list[0] ?? null)
      })
      .catch((e) => setError(e.message))
  }, [])

  const runSimulation = async (payload) => {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      setResult(await api.simulate(selected.id, payload))
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const submit = (event) => {
    event.preventDefault()
    const params = {}
    if (form.label) params.label = form.label
    if (form.url) params.url = form.url
    if (form.amount) params.amount_usd = Number(form.amount)
    runSimulation({ action_type: form.action_type, action_params: params, page_url: form.page_url })
  }

  const rules = selected?.rules ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-50">Policies</h1>
        <p className="mt-1 text-sm text-slate-400">
          The rules every proposed action is measured against. Highest priority wins; ties resolve
          to the most restrictive effect.
        </p>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      {policies.length > 1 && (
        <div className="max-w-sm">
          <label className="label" htmlFor="policy-select">
            Policy set
          </label>
          <select
            id="policy-select"
            className="input"
            value={selected?.id ?? ''}
            onChange={(e) => setSelected(policies.find((p) => p.id === Number(e.target.value)))}
          >
            {policies.map((policy) => (
              <option key={policy.id} value={policy.id}>
                {policy.name} (v{policy.version})
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <Panel
          title="Simulator"
          description="Test an action against this policy without running an agent."
          className="lg:col-span-2"
        >
          <form onSubmit={submit} className="space-y-3">
            <div>
              <label className="label" htmlFor="sim-action">
                Action
              </label>
              <select
                id="sim-action"
                className="input"
                value={form.action_type}
                onChange={(e) => setForm({ ...form, action_type: e.target.value })}
              >
                {ACTIONS.map((action) => (
                  <option key={action} value={action}>
                    {action}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="sim-label">
                Element label
              </label>
              <input
                id="sim-label"
                className="input"
                placeholder="e.g. Card number"
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label" htmlFor="sim-url">
                  Target URL
                </label>
                <input
                  id="sim-url"
                  className="input"
                  placeholder="https://…"
                  value={form.url}
                  onChange={(e) => setForm({ ...form, url: e.target.value })}
                />
              </div>
              <div>
                <label className="label" htmlFor="sim-amount">
                  Amount (USD)
                </label>
                <input
                  id="sim-amount"
                  className="input"
                  type="number"
                  min="0"
                  step="1"
                  value={form.amount}
                  onChange={(e) => setForm({ ...form, amount: e.target.value })}
                />
              </div>
            </div>
            <div>
              <label className="label" htmlFor="sim-page">
                Current page URL
              </label>
              <input
                id="sim-page"
                className="input"
                placeholder="https://portal/checkout"
                value={form.page_url}
                onChange={(e) => setForm({ ...form, page_url: e.target.value })}
              />
            </div>
            <button type="submit" className="btn-primary w-full" disabled={busy}>
              {busy ? 'Evaluating…' : 'Evaluate'}
            </button>
          </form>

          <div className="mt-4 border-t border-ink-700 pt-4">
            <p className="label">Quick scenarios</p>
            <div className="flex flex-wrap gap-1.5">
              {SCENARIOS.map((scenario) => (
                <button
                  key={scenario.label}
                  type="button"
                  className="rounded-full border border-ink-700 px-2.5 py-1 text-xs text-slate-400 hover:bg-ink-800 hover:text-slate-200"
                  onClick={() =>
                    runSimulation({
                      action_type: scenario.action_type,
                      action_params: scenario.params,
                    })
                  }
                >
                  {scenario.label}
                </button>
              ))}
            </div>
          </div>

          {result && (
            <div className="mt-4 rounded-lg border border-ink-700 bg-ink-950 p-3" aria-live="polite">
              <div className="flex items-center gap-3">
                <EffectBadge effect={result.effect} />
                <RiskMeter score={result.risk_score} />
              </div>
              <p className="mt-2 text-sm text-slate-300">{result.reason}</p>
              {result.matches.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {result.matches.map((match) => (
                    <li key={match.rule_id} className="text-xs text-slate-500">
                      <code className="font-mono text-slate-400">{match.rule_id}</code> ·{' '}
                      {match.effect} · priority {match.priority}
                    </li>
                  ))}
                </ul>
              )}
              {result.warnings.length > 0 && (
                <ul className="mt-2 space-y-1 text-xs text-gate">
                  {result.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </Panel>

        <Panel
          title={selected?.name ?? 'Rules'}
          description={`${rules.length} rules · default when nothing matches: ${selected?.default_effect ?? '—'}`}
          className="lg:col-span-3"
        >
          {rules.length === 0 ? (
            <Empty>This policy set has no rules.</Empty>
          ) : (
            <ul className="space-y-2">
              {[...rules]
                .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
                .map((rule) => (
                  <li key={rule.id} className="rounded-lg border border-ink-700 bg-ink-850 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <EffectBadge effect={rule.effect} />
                      <code className="font-mono text-xs text-slate-300">{rule.id}</code>
                      <span className="ml-auto text-xs text-slate-500">
                        priority {rule.priority ?? 0}
                      </span>
                      {rule.risk > 0 && <RiskMeter score={rule.risk} />}
                    </div>
                    {rule.description && (
                      <p className="mt-1.5 text-sm text-slate-400">{rule.description}</p>
                    )}
                    {rule.tags?.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {rule.tags.map((tag) => (
                          <span key={tag} className="chip bg-ink-800 text-slate-400">
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}
