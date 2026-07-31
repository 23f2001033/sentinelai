const EFFECT_STYLES = {
  allow: 'bg-allow/15 text-allow border border-allow/30',
  require_approval: 'bg-gate/15 text-gate border border-gate/30',
  deny: 'bg-deny/15 text-deny border border-deny/30',
}

const EFFECT_LABELS = {
  allow: 'Allowed',
  require_approval: 'Needs approval',
  deny: 'Blocked',
}

export function EffectBadge({ effect }) {
  return (
    <span className={`chip ${EFFECT_STYLES[effect] ?? 'bg-ink-800 text-slate-300'}`}>
      {EFFECT_LABELS[effect] ?? effect}
    </span>
  )
}

const STATUS_STYLES = {
  running: 'bg-accent/15 text-accent border border-accent/30',
  awaiting_approval: 'bg-gate/15 text-gate border border-gate/30',
  completed: 'bg-allow/15 text-allow border border-allow/30',
  succeeded: 'bg-allow/15 text-allow border border-allow/30',
  approved: 'bg-allow/15 text-allow border border-allow/30',
  failed: 'bg-deny/15 text-deny border border-deny/30',
  denied: 'bg-deny/15 text-deny border border-deny/30',
  blocked: 'bg-deny/15 text-deny border border-deny/30',
  cancelled: 'bg-ink-800 text-slate-400 border border-ink-700',
}

export function StatusPill({ status }) {
  const label = String(status ?? '').replace(/_/g, ' ')
  return (
    <span className={`chip ${STATUS_STYLES[status] ?? 'bg-ink-800 text-slate-300 border border-ink-700'}`}>
      {label || 'unknown'}
    </span>
  )
}

export function RiskMeter({ score }) {
  const value = Math.max(0, Math.min(100, Number(score) || 0))
  const tone = value >= 70 ? 'bg-deny' : value >= 35 ? 'bg-gate' : 'bg-allow'
  return (
    <div className="flex items-center gap-2">
      <div
        className="h-1.5 w-20 overflow-hidden rounded-full bg-ink-800"
        role="meter"
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Risk score"
      >
        <div className={`h-full ${tone}`} style={{ width: `${value}%` }} />
      </div>
      <span className="text-xs tabular-nums text-slate-400">{value}</span>
    </div>
  )
}

export function Panel({ title, description, actions, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-ink-700 px-5 py-4">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-100">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-slate-400">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="panel-pad">{children}</div>
    </section>
  )
}

export function Stat({ label, value, hint }) {
  return (
    <div className="panel panel-pad">
      <p className="text-xs uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-slate-50">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export function Empty({ children }) {
  return (
    <p className="rounded-lg border border-dashed border-ink-700 px-4 py-8 text-center text-sm text-slate-500">
      {children}
    </p>
  )
}

export function ErrorNote({ error, onDismiss }) {
  if (!error) return null
  return (
    <div role="alert" className="mb-4 rounded-lg border border-deny/40 bg-deny/10 px-4 py-3 text-sm text-red-200">
      <div className="flex items-start justify-between gap-3">
        <span>{String(error)}</span>
        {onDismiss && (
          <button type="button" onClick={onDismiss} className="text-red-200/70 hover:text-red-100">
            Dismiss
          </button>
        )}
      </div>
    </div>
  )
}

export function timeOf(value) {
  if (!value) return ''
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function money(value) {
  const n = Number(value) || 0
  return n < 0.01 && n > 0 ? `$${n.toFixed(4)}` : `$${n.toFixed(2)}`
}
