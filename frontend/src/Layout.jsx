import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from './api'
import { useLiveEvents } from './hooks/useLiveEvents'

const NAV = [
  { to: '/', label: 'Overview', end: true },
  { to: '/approvals', label: 'Approvals' },
  { to: '/policies', label: 'Policies' },
  { to: '/spend', label: 'Spend' },
]

export default function Layout() {
  const [pending, setPending] = useState(0)
  const [health, setHealth] = useState(null)

  const refresh = () => {
    api.stats().then((s) => setPending(s.pending_approvals)).catch(() => {})
  }

  useEffect(() => {
    refresh()
    api.health().then(setHealth).catch(() => {})
  }, [])

  const connected = useLiveEvents('/ws/all', (event) => {
    if (event.kind === 'approval_requested' || event.kind === 'approval_resolved') refresh()
  })

  return (
    <div className="min-h-screen">
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      <header className="sticky top-0 z-30 border-b border-ink-700 bg-ink-950/90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-8 gap-y-3 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <ShieldMark />
            <div>
              <p className="text-sm font-semibold leading-tight text-slate-50">SentinelAI</p>
              <p className="text-[11px] leading-tight text-slate-500">AI governance console</p>
            </div>
          </div>

          <nav aria-label="Primary" className="flex flex-wrap items-center gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
                    isActive ? 'bg-ink-800 text-slate-50' : 'text-slate-400 hover:text-slate-100'
                  }`
                }
              >
                {item.label}
                {item.to === '/approvals' && pending > 0 && (
                  <span className="ml-2 rounded-full bg-gate px-1.5 py-0.5 text-[11px] font-bold text-ink-950">
                    {pending}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-3 text-xs text-slate-500">
            <a
              href="/demo/"
              target="_blank"
              rel="noreferrer"
              className="rounded-lg border border-ink-700 px-3 py-1.5 text-slate-300 hover:bg-ink-800"
            >
              Sandbox site
            </a>
            <span className="flex items-center gap-1.5" title={connected ? 'Live' : 'Reconnecting'}>
              <span
                className={`h-2 w-2 rounded-full ${connected ? 'bg-allow' : 'bg-slate-600'}`}
                aria-hidden="true"
              />
              <span className="sr-only">Event stream:</span>
              {connected ? 'Live' : 'Offline'}
            </span>
          </div>
        </div>
      </header>

      {health && !health.planner_configured && (
        <div role="status" className="border-b border-gate/30 bg-gate/10 px-4 py-2 text-center text-xs text-amber-200">
          No API key for {health.planner_provider ?? 'the planner'} — new runs will fail. Add one to{' '}
          <code className="font-mono">backend/.env</code>
          {health.planner_signup_url && (
            <>
              {' '}
              (free key:{' '}
              <a href={health.planner_signup_url} target="_blank" rel="noreferrer" className="underline">
                {health.planner_signup_url}
              </a>
              )
            </>
          )}
          . Policy simulation and the audit trail still work without it.
        </div>
      )}

      <main id="main" className="mx-auto max-w-7xl px-4 py-6 sm:px-6">
        <Outlet />
      </main>
    </div>
  )
}

function ShieldMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path
        d="M12 2.5 4.5 5.5v6c0 4.6 3.2 8.9 7.5 10 4.3-1.1 7.5-5.4 7.5-10v-6L12 2.5Z"
        stroke="#4c8dff"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="m8.6 12.1 2.4 2.4 4.4-4.7" stroke="#37d399" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
