import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useLiveEvents } from '../hooks/useLiveEvents'
import {
  EffectBadge,
  Empty,
  ErrorNote,
  Panel,
  RiskMeter,
  StatusPill,
  money,
  timeOf,
} from '../components/ui'

const TERMINAL = new Set(['completed', 'failed', 'cancelled'])

export default function RunDetail() {
  const { runId } = useParams()
  const [run, setRun] = useState(null)
  const [audit, setAudit] = useState([])
  const [error, setError] = useState(null)
  const [showAudit, setShowAudit] = useState(false)
  const [deciding, setDeciding] = useState(null)

  const refresh = useCallback(() => {
    api.getRun(runId).then(setRun).catch((e) => setError(e.message))
    api.getRunAudit(runId).then(setAudit).catch(() => {})
  }, [runId])

  useEffect(() => {
    refresh()
  }, [refresh])

  const connected = useLiveEvents(`/ws/runs/${runId}`, refresh)

  const decide = async (approvalId, decision) => {
    setDeciding(approvalId)
    setError(null)
    try {
      await api.decideApproval(approvalId, { decision, decided_by: 'console user' })
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setDeciding(null)
    }
  }

  const cancel = async () => {
    try {
      await api.cancelRun(runId)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  if (!run) {
    return <p className="text-sm text-slate-400">Loading run…</p>
  }

  const spend = audit
    .filter((e) => e.kind === 'llm_call')
    .reduce((total, e) => total + (Number(e.payload?.cost_usd) || 0), 0)
  const isTerminal = TERMINAL.has(run.status)

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to="/" className="text-xs text-slate-500 hover:text-slate-300">
            ← Back to overview
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-slate-50">Run #{run.id}</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-400">{run.goal}</p>
          {run.summary && <p className="mt-2 text-sm text-slate-300">{run.summary}</p>}
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-slate-500">{connected ? 'Live' : 'Reconnecting…'}</span>
          <StatusPill status={run.status} />
          {!isTerminal && (
            <button type="button" onClick={cancel} className="btn-ghost">
              Cancel run
            </button>
          )}
        </div>
      </div>

      <ErrorNote error={error} onDismiss={() => setError(null)} />

      <div className="grid gap-4 sm:grid-cols-3">
        <div className="panel panel-pad">
          <p className="text-xs uppercase tracking-wide text-slate-400">Steps</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{run.steps.length}</p>
        </div>
        <div className="panel panel-pad">
          <p className="text-xs uppercase tracking-wide text-slate-400">Gated by policy</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">
            {run.steps.filter((s) => s.decision && s.decision.effect !== 'allow').length}
          </p>
        </div>
        <div className="panel panel-pad">
          <p className="text-xs uppercase tracking-wide text-slate-400">Model spend</p>
          <p className="mt-1 text-2xl font-semibold tabular-nums">{money(spend)}</p>
        </div>
      </div>

      <Panel
        title="Governed timeline"
        description="Every step the agent proposed, the policy decision, and what happened next."
        actions={
          <button type="button" onClick={() => setShowAudit((v) => !v)} className="btn-ghost">
            {showAudit ? 'Hide raw audit' : 'Show raw audit'}
          </button>
        }
      >
        <div aria-live="polite" aria-atomic="false">
          {run.steps.length === 0 ? (
            <Empty>Waiting for the agent's first step…</Empty>
          ) : (
            <ol className="space-y-3">
              {run.steps.map((step) => (
                <StepCard
                  key={step.id}
                  step={step}
                  onDecide={decide}
                  deciding={deciding === step.approval?.id}
                />
              ))}
            </ol>
          )}
        </div>
      </Panel>

      {showAudit && (
        <Panel title="Raw audit trail" description={`${audit.length} events, oldest first`}>
          <ol className="space-y-1.5 font-mono text-xs">
            {audit.map((event) => (
              <li key={event.id} className="flex gap-3 rounded px-2 py-1 hover:bg-ink-850">
                <span className="shrink-0 text-slate-600">{timeOf(event.created_at)}</span>
                <span className="w-40 shrink-0 text-accent">{event.kind}</span>
                <span className="min-w-0 flex-1 text-slate-300">{event.message}</span>
                <span className="shrink-0 text-slate-600">{event.actor}</span>
              </li>
            ))}
          </ol>
        </Panel>
      )}
    </div>
  )
}

function StepCard({ step, onDecide, deciding }) {
  const decision = step.decision
  const approval = step.approval
  const isPending = approval?.status === 'pending'
  const params = step.action_params ?? {}
  const target = params.label || params.url || params.summary || ''

  return (
    <li
      className={`rounded-xl border bg-ink-850 p-4 ${
        isPending ? 'border-gate/50 shadow-[0_0_0_1px_rgba(245,185,66,0.15)]' : 'border-ink-700'
      }`}
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-800 text-xs font-semibold tabular-nums text-slate-400">
          {step.index}
        </span>

        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm">
            <code className="rounded bg-ink-800 px-1.5 py-0.5 font-mono text-xs text-accent">
              {step.action_type}
            </code>
            {target && <span className="truncate text-slate-200">{target}</span>}
          </p>

          {step.rationale && <p className="mt-1.5 text-sm text-slate-400">{step.rationale}</p>}

          {decision && (
            <div className="mt-3 rounded-lg border border-ink-700 bg-ink-900 p-3">
              <div className="flex flex-wrap items-center gap-3">
                <EffectBadge effect={decision.effect} />
                <span className="text-xs text-slate-400">{decision.reason}</span>
                {decision.matched_rules?.length > 0 && (
                  <RiskMeter score={Math.max(...decision.matched_rules.map((r) => r.risk ?? 0))} />
                )}
              </div>
              {decision.matched_rules?.length > 0 ? (
                <p className="mt-2 text-xs text-slate-500">
                  Matched:{' '}
                  {decision.matched_rules.map((rule, i) => (
                    <span key={rule.rule_id}>
                      {i > 0 && ', '}
                      <code className="font-mono text-slate-400">{rule.rule_id}</code>
                    </span>
                  ))}
                </p>
              ) : (
                <p className="mt-2 text-xs text-slate-500">
                  No rule matched — the policy default applied.
                </p>
              )}
            </div>
          )}

          {isPending && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="btn-allow"
                disabled={deciding}
                onClick={() => onDecide(approval.id, 'approved')}
              >
                Approve
              </button>
              <button
                type="button"
                className="btn-deny"
                disabled={deciding}
                onClick={() => onDecide(approval.id, 'denied')}
              >
                Deny
              </button>
              <span className="text-xs text-slate-500">The run is paused until you decide.</span>
            </div>
          )}

          {approval && !isPending && (
            <p className="mt-2 text-xs text-slate-500">
              {approval.status === 'approved' ? 'Approved' : 'Denied'} by{' '}
              {approval.decided_by || 'a reviewer'}
              {approval.note ? ` — "${approval.note}"` : ''}
            </p>
          )}

          {step.error && (
            <p className="mt-2 rounded border border-deny/30 bg-deny/10 px-2 py-1 text-xs text-red-200">
              {step.error}
            </p>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-end gap-1.5">
          <StatusPill status={step.status} />
          {step.duration_ms != null && (
            <span className="text-xs tabular-nums text-slate-600">{step.duration_ms} ms</span>
          )}
        </div>
      </div>
    </li>
  )
}
